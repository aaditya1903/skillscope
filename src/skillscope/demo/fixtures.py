"""A local ingestion client over committed synthetic demonstration skills.

The demonstration corpus exists so a clean clone can start the stack, load a
corpus, build indexes and answer a search without a GitHub token, a network
call or a model download. It reuses the real discovery manifest, ingestion
runner, parser and snapshot writer, so the path being demonstrated is the real
one; only the transport is replaced.

The fixtures are original SkillScope content under this repository's MIT
licence. No upstream third-party skill is redistributed here.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from skillscope.ingestion.github_client import GitHubNotFoundError, GitHubResponse
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

DEMO_REPOSITORY_OWNER = "aaditya1903"
DEMO_REPOSITORY_NAME = "skillscope"
DEMO_REPOSITORY_FULL_NAME = f"{DEMO_REPOSITORY_OWNER}/{DEMO_REPOSITORY_NAME}"
DEMO_REPOSITORY_ID = 1
DEMO_BRANCH = "main"
DEMO_FIXTURE_ROOT = "data/demo/skills"
DEMO_QUERY = "path:data/demo/skills filename:SKILL.md"
MAX_FIXTURE_BYTES = 256 * 1024

# The demonstration corpus is committed rather than discovered, so its identity
# is fixed rather than taken from a GitHub run.
DEMO_GIT_COMMIT = "0" * 40
DEMO_GENERATED_AT = datetime(2026, 1, 1, tzinfo=UTC)

_RATE_LIMIT = GitHubRateLimitSnapshot(
    limit=5_000,
    used=0,
    remaining=5_000,
    reset_at=datetime(2030, 1, 1, tzinfo=UTC),
    resource="core",
    retry_after_seconds=None,
)


def _blob_sha(content: bytes) -> str:
    """Compute the Git blob SHA-1 so fixture identity matches Git's own."""

    header = f"blob {len(content)}\0".encode()
    return hashlib.sha1(header + content, usedforsecurity=False).hexdigest()


def _iter_fixture_directories(root: Path) -> Iterator[Path]:
    for directory in sorted(path for path in root.iterdir() if path.is_dir()):
        if (directory / "SKILL.md").is_file():
            yield directory


def _repository_relative(path: Path, project_root: Path) -> str:
    return path.relative_to(project_root).as_posix()


def build_demo_manifest(project_root: Path) -> CandidateManifest:
    """Describe every committed fixture skill as an ordinary candidate manifest."""

    root = project_root / DEMO_FIXTURE_ROOT
    if not root.is_dir():
        raise FileNotFoundError(f"demonstration fixtures are missing: {root}")

    candidates: list[CandidateManifestCandidate] = []
    for directory in _iter_fixture_directories(root):
        skill_path = directory / "SKILL.md"
        content = skill_path.read_bytes()
        if len(content) > MAX_FIXTURE_BYTES:
            raise ValueError(f"demonstration fixture exceeds the size cap: {skill_path}")
        relative = _repository_relative(skill_path, project_root)
        candidates.append(
            CandidateManifestCandidate(
                repository_id=DEMO_REPOSITORY_ID,
                repository_full_name=DEMO_REPOSITORY_FULL_NAME,
                repository_html_url=f"https://github.com/{DEMO_REPOSITORY_FULL_NAME}",
                path=relative,
                git_blob_sha=_blob_sha(content),
                html_url=(
                    f"https://github.com/{DEMO_REPOSITORY_FULL_NAME}/blob/{DEMO_BRANCH}/{relative}"
                ),
                matched_queries=(DEMO_QUERY,),
            )
        )

    if not candidates:
        raise FileNotFoundError("the demonstration fixture directory contains no skills")

    return CandidateManifest(
        header=CandidateManifestHeader(
            generated_at=DEMO_GENERATED_AT,
            git_commit=DEMO_GIT_COMMIT,
            target_skills=len(candidates),
            target_reached=True,
            candidate_count=len(candidates),
            page_count=0,
            seed_repositories=(DEMO_REPOSITORY_FULL_NAME,),
            queries=(DEMO_QUERY,),
        ),
        pages=(),
        candidates=tuple(candidates),
    )


class LocalFixtureClient:
    """Serve the committed fixtures through the read-only ingestion boundary.

    Every method returns the same payload shapes the GitHub client returns, so
    the runner cannot tell the difference and no transport code is bypassed for
    the demonstration.
    """

    def __init__(self, project_root: Path) -> None:
        self.project_root = project_root.resolve()
        self.fixture_root = (self.project_root / DEMO_FIXTURE_ROOT).resolve()

    def _resolve(self, path: str) -> Path:
        candidate = (self.project_root / PurePosixPath(path)).resolve()
        if not candidate.is_relative_to(self.fixture_root):
            raise GitHubNotFoundError(
                "the requested path is outside the demonstration corpus",
                correlation_id="demonstration",
            )
        return candidate

    async def get_rate_limits(self) -> GitHubResponse[GitHubRateLimitResponsePayload]:
        """Report a static budget; the demonstration makes no network request."""

        payload = GitHubRateLimitResponsePayload.model_validate(
            {
                "resources": {
                    name: {"limit": limit, "used": 0, "remaining": limit, "reset": 1}
                    for name, limit in (("core", 5_000), ("search", 30), ("code_search", 10))
                }
            }
        )
        return self._response(payload)

    async def get_repository(
        self,
        owner: str,
        repository: str,
    ) -> GitHubResponse[GitHubRepositoryPayload]:
        """Return fixed metadata for the single repository that holds the fixtures."""

        if f"{owner}/{repository}" != DEMO_REPOSITORY_FULL_NAME:
            raise GitHubNotFoundError(
                "only the demonstration repository is available",
                correlation_id="demonstration",
            )
        payload = GitHubRepositoryPayload.model_validate(
            {
                "id": DEMO_REPOSITORY_ID,
                "owner": {
                    "login": DEMO_REPOSITORY_OWNER,
                    "id": DEMO_REPOSITORY_ID,
                    "html_url": f"https://github.com/{DEMO_REPOSITORY_OWNER}",
                },
                "name": DEMO_REPOSITORY_NAME,
                "full_name": DEMO_REPOSITORY_FULL_NAME,
                "private": False,
                "html_url": f"https://github.com/{DEMO_REPOSITORY_FULL_NAME}",
                "default_branch": DEMO_BRANCH,
                "description": "SkillScope demonstration corpus.",
                "stargazers_count": 0,
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
                "pushed_at": DEMO_GENERATED_AT.isoformat().replace("+00:00", "Z"),
            }
        )
        return self._response(payload)

    async def get_file(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
        *,
        etag: str | None = None,
    ) -> GitHubResponse[GitHubFilePayload]:
        """Return one fixture file encoded exactly as the contents API would."""

        del ref, etag
        if f"{owner}/{repository}" != DEMO_REPOSITORY_FULL_NAME:
            raise GitHubNotFoundError(
                "only the demonstration repository is available",
                correlation_id="demonstration",
            )
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise GitHubNotFoundError(
                "the requested demonstration file does not exist",
                correlation_id="demonstration",
            )
        content = resolved.read_bytes()
        payload = GitHubFilePayload.model_validate(
            {
                "type": "file",
                "name": resolved.name,
                "path": path,
                "sha": _blob_sha(content),
                "size": len(content),
                "encoding": "base64",
                "content": base64.b64encode(content).decode("ascii"),
                "url": (
                    f"https://api.github.com/repos/{DEMO_REPOSITORY_FULL_NAME}/contents/{path}"
                ),
                "git_url": (
                    f"https://api.github.com/repos/{DEMO_REPOSITORY_FULL_NAME}"
                    f"/git/blobs/{_blob_sha(content)}"
                ),
                "html_url": (
                    f"https://github.com/{DEMO_REPOSITORY_FULL_NAME}/blob/{DEMO_BRANCH}/{path}"
                ),
            }
        )
        return self._response(payload)

    async def list_directory(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
    ) -> GitHubResponse[tuple[GitHubDirectoryEntryPayload, ...]]:
        """List one skill directory, matching the bounded non-recursive GitHub call."""

        del ref
        if f"{owner}/{repository}" != DEMO_REPOSITORY_FULL_NAME:
            raise GitHubNotFoundError(
                "only the demonstration repository is available",
                correlation_id="demonstration",
            )
        resolved = self._resolve(path)
        if not resolved.is_dir():
            raise GitHubNotFoundError(
                "the requested demonstration directory does not exist",
                correlation_id="demonstration",
            )

        entries = []
        for child in sorted(resolved.iterdir()):
            relative = _repository_relative(child, self.project_root)
            is_directory = child.is_dir()
            content = b"" if is_directory else child.read_bytes()
            entries.append(
                GitHubDirectoryEntryPayload.model_validate(
                    {
                        "type": "dir" if is_directory else "file",
                        "name": child.name,
                        "path": relative,
                        "sha": _blob_sha(content),
                        "size": 0 if is_directory else len(content),
                        "url": (
                            f"https://api.github.com/repos/{DEMO_REPOSITORY_FULL_NAME}"
                            f"/contents/{relative}"
                        ),
                        "git_url": (
                            f"https://api.github.com/repos/{DEMO_REPOSITORY_FULL_NAME}"
                            f"/git/{'trees' if is_directory else 'blobs'}/{_blob_sha(content)}"
                        ),
                        "html_url": (
                            f"https://github.com/{DEMO_REPOSITORY_FULL_NAME}"
                            f"/{'tree' if is_directory else 'blob'}/{DEMO_BRANCH}/{relative}"
                        ),
                    }
                )
            )
        return self._response(tuple(entries))

    @staticmethod
    def _response[PayloadT](payload: PayloadT) -> GitHubResponse[PayloadT]:
        return GitHubResponse(
            data=payload,
            status_code=200,
            etag=None,
            rate_limit=_RATE_LIMIT,
            correlation_id="demonstration",
        )
