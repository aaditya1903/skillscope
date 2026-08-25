"""PostgreSQL-backed evidence for idempotent ingestion orchestration."""

from __future__ import annotations

import base64
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from skillscope.db.enums import IngestionItemStatus, IngestionRunStatus, ValidationStatus
from skillscope.db.models import IngestionRun, IngestionRunItem, Repository, Skill
from skillscope.ingestion.github_client import (
    GitHubPayloadTooLargeError,
    GitHubResponse,
)
from skillscope.ingestion.manifest import (
    CandidateManifest,
    CandidateManifestCandidate,
    CandidateManifestHeader,
)
from skillscope.ingestion.models import (
    GitHubDirectoryEntryPayload,
    GitHubFilePayload,
    GitHubRateLimitResponsePayload,
    GitHubRepositoryPayload,
)
from skillscope.ingestion.rate_limit import GitHubRateLimitSnapshot
from skillscope.ingestion.runner import IngestionClient, run_ingestion

pytestmark = pytest.mark.integration

GIT_COMMIT = "c" * 40
QUERY = "description filename:SKILL.md repo:skillscope-tests/catalogue"
RATE_LIMIT = GitHubRateLimitSnapshot(
    limit=5_000,
    used=1,
    remaining=4_999,
    reset_at=datetime(2030, 1, 1, tzinfo=UTC),
    resource="core",
    retry_after_seconds=None,
)


class FakeIngestionClient(IngestionClient):
    """In-memory GitHub boundary containing only synthetic test data."""

    def __init__(self) -> None:
        self.repositories: dict[str, GitHubRepositoryPayload] = {}
        self.files: dict[tuple[str, str], tuple[str, bytes]] = {}
        self.file_errors: dict[tuple[str, str], Exception] = {}
        self.file_requests = 0
        self.directory_requests = 0

    def add_repository(
        self,
        full_name: str,
        repository_id: int,
        *,
        private: bool = False,
    ) -> None:
        owner, name = full_name.split("/", maxsplit=1)
        self.repositories[full_name] = GitHubRepositoryPayload.model_validate(
            {
                "id": repository_id,
                "owner": {
                    "login": owner,
                    "id": repository_id + 10_000,
                    "html_url": f"https://github.com/{owner}",
                },
                "name": name,
                "full_name": full_name,
                "private": private,
                "html_url": f"https://github.com/{full_name}",
                "default_branch": "main",
                "description": "Synthetic ingestion integration fixture.",
                "stargazers_count": 1,
                "forks_count": 0,
                "open_issues_count": 0,
                "fork": False,
                "archived": False,
                "license": {
                    "key": "mit",
                    "name": "MIT License",
                    "spdx_id": "MIT",
                    "url": "https://api.github.com/licenses/mit",
                },
                "pushed_at": "2030-01-01T00:00:00Z",
            }
        )

    def add_file(self, full_name: str, path: str, sha: str, content: bytes) -> None:
        self.files[(full_name, path)] = (sha, content)

    async def get_rate_limits(self) -> GitHubResponse[GitHubRateLimitResponsePayload]:
        payload = GitHubRateLimitResponsePayload.model_validate(
            {
                "resources": {
                    name: {"limit": limit, "used": 1, "remaining": limit - 1, "reset": 1}
                    for name, limit in (("core", 5_000), ("search", 30), ("code_search", 10))
                }
            }
        )
        return _response(payload)

    async def get_repository(
        self,
        owner: str,
        repository: str,
    ) -> GitHubResponse[GitHubRepositoryPayload]:
        return _response(self.repositories[f"{owner}/{repository}"], etag='"repository"')

    async def get_file(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
        *,
        etag: str | None = None,
    ) -> GitHubResponse[GitHubFilePayload]:
        del ref, etag
        self.file_requests += 1
        full_name = f"{owner}/{repository}"
        error = self.file_errors.get((full_name, path))
        if error is not None:
            raise error
        sha, content = self.files[(full_name, path)]
        encoded = base64.b64encode(content).decode("ascii")
        payload = GitHubFilePayload.model_validate(
            {
                "type": "file",
                "name": "SKILL.md",
                "path": path,
                "sha": sha,
                "size": len(content),
                "encoding": "base64",
                "content": encoded,
                "url": f"https://api.github.com/repos/{full_name}/contents/{path}",
                "git_url": f"https://api.github.com/repos/{full_name}/git/blobs/{sha}",
                "html_url": f"https://github.com/{full_name}/blob/main/{path}",
            }
        )
        return _response(payload, etag='"file"')

    async def list_directory(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
    ) -> GitHubResponse[tuple[GitHubDirectoryEntryPayload, ...]]:
        del ref
        self.directory_requests += 1
        full_name = f"{owner}/{repository}"
        skill_path = f"{path}/SKILL.md" if path else "SKILL.md"
        sha, content = self.files[(full_name, skill_path)]
        payload = (
            GitHubDirectoryEntryPayload.model_validate(
                {
                    "type": "file",
                    "name": "SKILL.md",
                    "path": skill_path,
                    "sha": sha,
                    "size": len(content),
                    "url": f"https://api.github.com/repos/{full_name}/contents/{skill_path}",
                    "git_url": f"https://api.github.com/repos/{full_name}/git/blobs/{sha}",
                    "html_url": f"https://github.com/{full_name}/blob/main/{skill_path}",
                }
            ),
            GitHubDirectoryEntryPayload.model_validate(
                {
                    "type": "dir",
                    "name": "scripts",
                    "path": f"{path}/scripts" if path else "scripts",
                    "sha": "d" * 40,
                    "size": 0,
                    "url": f"https://api.github.com/repos/{full_name}/contents/{path}/scripts",
                    "git_url": f"https://api.github.com/repos/{full_name}/git/trees/{'d' * 40}",
                    "html_url": f"https://github.com/{full_name}/tree/main/{path}/scripts",
                }
            ),
        )
        return _response(payload)


def _response[PayloadT](
    payload: PayloadT,
    *,
    etag: str | None = None,
) -> GitHubResponse[PayloadT]:
    return GitHubResponse(
        data=payload,
        status_code=200,
        etag=etag,
        rate_limit=RATE_LIMIT,
        correlation_id="integration-correlation",
    )


def _manifest(
    candidates: list[tuple[int, str, str, str]],
) -> CandidateManifest:
    records = tuple(
        CandidateManifestCandidate(
            repository_id=repository_id,
            repository_full_name=full_name,
            repository_html_url=f"https://github.com/{full_name}",
            path=path,
            git_blob_sha=sha,
            html_url=f"https://github.com/{full_name}/blob/main/{path}",
            matched_queries=(QUERY,),
        )
        for repository_id, full_name, path, sha in candidates
    )
    return CandidateManifest(
        header=CandidateManifestHeader(
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="a" * 40,
            target_skills=len(records),
            target_reached=True,
            candidate_count=len(records),
            page_count=0,
            seed_repositories=("skillscope-tests/catalogue",),
            queries=(QUERY,),
        ),
        pages=(),
        candidates=records,
    )


def _skill_content(name: str, description: str = "Synthetic valid skill.") -> bytes:
    return (
        f"---\nname: {name}\ndescription: {description}\n---\n\n"
        f"# {name.title()}\n\nUse this inert integration fixture safely.\n"
    ).encode()


def _factory(db_session: Session) -> Callable[[], Session]:
    return sessionmaker(
        bind=db_session.connection(),
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )


@pytest.mark.asyncio
async def test_identical_second_run_is_unchanged_without_duplicates(
    db_session: Session,
) -> None:
    client = FakeIngestionClient()
    full_name = "skillscope-tests/catalogue"
    path = "skills/alpha/SKILL.md"
    sha = "1" * 40
    client.add_repository(full_name, 501)
    client.add_file(full_name, path, sha, _skill_content("alpha"))
    manifest = _manifest([(501, full_name, path, sha)])
    factory = _factory(db_session)

    first = await run_ingestion(
        client,
        factory,
        manifest,
        manifest_path=Path("data/manifests/candidates.jsonl"),
        git_commit_sha=GIT_COMMIT,
    )
    second = await run_ingestion(
        client,
        factory,
        manifest,
        manifest_path=Path("data/manifests/candidates.jsonl"),
        git_commit_sha=GIT_COMMIT,
    )

    with factory() as verification:
        skill_count = verification.scalar(select(func.count()).select_from(Skill))
        repository_count = verification.scalar(select(func.count()).select_from(Repository))
        runs = verification.scalars(
            select(IngestionRun).order_by(IngestionRun.started_at, IngestionRun.id)
        ).all()

    assert first.ingested_count == 1
    assert second.unchanged_count == 1
    assert second.outcomes[0].status is IngestionItemStatus.UNCHANGED
    assert skill_count == 1
    assert repository_count == 1
    assert client.file_requests == 1
    assert client.directory_requests == 1
    assert len(runs) == 2
    assert all(run.status is IngestionRunStatus.COMPLETED for run in runs)


@pytest.mark.asyncio
async def test_repository_root_skill_is_ingested_with_an_unverifiable_name_warning(
    db_session: Session,
) -> None:
    client = FakeIngestionClient()
    full_name = "skillscope-tests/root-catalogue"
    path = "SKILL.md"
    sha = "9" * 40
    client.add_repository(full_name, 509)
    client.add_file(full_name, path, sha, _skill_content("portable-root-skill"))
    factory = _factory(db_session)

    summary = await run_ingestion(
        client,
        factory,
        _manifest([(509, full_name, path, sha)]),
        manifest_path=Path("data/manifests/root-candidate.jsonl"),
        git_commit_sha=GIT_COMMIT,
    )

    with factory() as verification:
        skill = verification.scalar(
            select(Skill)
            .join(Repository, Skill.repository_id == Repository.id)
            .where(
                Repository.github_repository_id == 509,
                Skill.path == path,
            )
        )

    assert summary.ingested_count == 1
    assert summary.invalid_count == 0
    assert skill is not None
    assert skill.validation_status is ValidationStatus.WARNING
    assert {message["code"] for message in skill.validation_messages_json} == {
        "root_directory_name_unverified"
    }


@pytest.mark.asyncio
async def test_changed_sha_updates_the_existing_skill(db_session: Session) -> None:
    client = FakeIngestionClient()
    full_name = "skillscope-tests/catalogue"
    path = "skills/alpha/SKILL.md"
    client.add_repository(full_name, 502)
    client.add_file(full_name, path, "2" * 40, _skill_content("alpha", "Version one."))
    factory = _factory(db_session)

    await run_ingestion(
        client,
        factory,
        _manifest([(502, full_name, path, "2" * 40)]),
        manifest_path=Path("data/manifests/first.jsonl"),
        git_commit_sha=GIT_COMMIT,
    )
    client.add_file(full_name, path, "3" * 40, _skill_content("alpha", "Version two."))
    second = await run_ingestion(
        client,
        factory,
        _manifest([(502, full_name, path, "3" * 40)]),
        manifest_path=Path("data/manifests/second.jsonl"),
        git_commit_sha=GIT_COMMIT,
    )

    with factory() as verification:
        skills = verification.scalars(select(Skill)).all()

    assert second.ingested_count == 1
    assert len(skills) == 1
    assert skills[0].git_blob_sha == "3" * 40
    assert skills[0].description == "Version two."
    assert skills[0].embedding is None
    assert skills[0].embedding_model_id is None
    assert skills[0].embedding_model_revision is None
    assert skills[0].embedding_config_sha256 is None
    assert skills[0].embedding_content_sha256 is None
    assert skills[0].embedding_text_sha256 is None
    assert skills[0].indexed_at is None


@pytest.mark.asyncio
async def test_invalid_candidate_is_tracked_without_inventing_required_fields(
    db_session: Session,
) -> None:
    client = FakeIngestionClient()
    full_name = "skillscope-tests/catalogue"
    path = "skills/invalid/SKILL.md"
    sha = "4" * 40
    invalid_content = b"---\nname: invalid\n---\n\nMissing description.\n"
    client.add_repository(full_name, 503)
    client.add_file(full_name, path, sha, invalid_content)
    factory = _factory(db_session)

    summary = await run_ingestion(
        client,
        factory,
        _manifest([(503, full_name, path, sha)]),
        manifest_path=Path("data/manifests/invalid.jsonl"),
        git_commit_sha=GIT_COMMIT,
    )

    with factory() as verification:
        skill_count = verification.scalar(select(func.count()).select_from(Skill))
        item = verification.scalar(
            select(IngestionRunItem).where(IngestionRunItem.ingestion_run_id == summary.run_id)
        )

    assert summary.invalid_count == 1
    assert summary.parsed_count == 1
    assert skill_count == 0
    assert item is not None
    assert item.status is IngestionItemStatus.INVALID
    assert item.reason is not None
    assert json.loads(item.reason)["category"] == "validation"


@pytest.mark.asyncio
async def test_per_item_failure_is_safe_and_does_not_stop_later_candidates(
    db_session: Session,
) -> None:
    client = FakeIngestionClient()
    full_name = "skillscope-tests/catalogue"
    failed_path = "skills/alpha/SKILL.md"
    valid_path = "skills/beta/SKILL.md"
    failed_sha = "5" * 40
    valid_sha = "6" * 40
    secret = "github_pat_NEVER_STORE_THIS"
    client.add_repository(full_name, 504)
    client.add_file(full_name, failed_path, failed_sha, _skill_content("alpha"))
    client.add_file(full_name, valid_path, valid_sha, _skill_content("beta"))
    client.file_errors[(full_name, failed_path)] = GitHubPayloadTooLargeError(
        secret,
        correlation_id="safe-correlation",
        status_code=200,
    )
    factory = _factory(db_session)

    summary = await run_ingestion(
        client,
        factory,
        _manifest(
            [
                (504, full_name, failed_path, failed_sha),
                (504, full_name, valid_path, valid_sha),
            ]
        ),
        manifest_path=Path("data/manifests/partial.jsonl"),
        git_commit_sha=GIT_COMMIT,
    )

    with factory() as verification:
        items = verification.scalars(
            select(IngestionRunItem)
            .where(IngestionRunItem.ingestion_run_id == summary.run_id)
            .order_by(IngestionRunItem.path)
        ).all()
        skill_count = verification.scalar(select(func.count()).select_from(Skill))

    assert summary.discovered_count == 2
    assert summary.error_count == 1
    assert summary.ingested_count == 1
    assert skill_count == 1
    assert [item.status for item in items] == [
        IngestionItemStatus.ERROR,
        IngestionItemStatus.INGESTED,
    ]
    assert items[0].reason is not None
    assert json.loads(items[0].reason) == {
        "category": "payload_too_large",
        "correlation_id": "safe-correlation",
        "message": "GitHub content exceeded an ingestion safety limit.",
    }
    assert secret not in items[0].reason
