"""Idempotent orchestration from a candidate manifest into PostgreSQL."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path, PurePosixPath
from time import perf_counter
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from skillscope.db.enums import IngestionItemStatus, IngestionRunStatus, ValidationStatus
from skillscope.db.models import IngestionRun, IngestionRunItem
from skillscope.ingestion.discovery import SkillCandidate
from skillscope.ingestion.github_client import (
    GitHubAuthenticationError,
    GitHubClientError,
    GitHubNotFoundError,
    GitHubNotModifiedResponse,
    GitHubPayloadError,
    GitHubPayloadTooLargeError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubResponse,
    GitHubTransportError,
)
from skillscope.ingestion.manifest import (
    CandidateManifest,
    serialize_candidate_manifest,
)
from skillscope.ingestion.models import (
    GitHubDirectoryEntryPayload,
    GitHubFilePayload,
    GitHubRateLimitResponsePayload,
    GitHubRepositoryPayload,
)
from skillscope.ingestion.persistence import (
    ExistingSkill,
    PersistenceConflictError,
    RepositoryContext,
    find_existing_skill,
    mark_skill_seen,
    upsert_repository,
    upsert_skill,
)
from skillscope.parsing import (
    DirectoryEntryKind,
    ParsedSkill,
    SkillDirectoryEntry,
    SkillParser,
    SkillSource,
)

_GIT_COMMIT_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class IngestionClient(Protocol):
    """Read-only GitHub operations required by one ingestion run."""

    async def get_rate_limits(self) -> GitHubResponse[GitHubRateLimitResponsePayload]: ...

    async def get_repository(
        self,
        owner: str,
        repository: str,
    ) -> GitHubResponse[GitHubRepositoryPayload]: ...

    async def get_file(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
        *,
        etag: str | None = None,
    ) -> GitHubResponse[GitHubFilePayload] | GitHubNotModifiedResponse: ...

    async def list_directory(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
    ) -> GitHubResponse[tuple[GitHubDirectoryEntryPayload, ...]]: ...


type SessionFactory = Callable[[], Session]


class IngestionFailureCategory(StrEnum):
    """Stable categories suitable for stored run evidence and aggregation."""

    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    TRANSPORT = "transport"
    PAYLOAD = "payload"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    CANDIDATE_CHANGED = "candidate_changed"
    PRIVATE_REPOSITORY = "private_repository"
    VALIDATION = "validation"
    PERSISTENCE = "persistence"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class IngestionItemOutcome:
    """One safe, body-free candidate outcome returned by the runner."""

    repository_full_name: str
    path: str
    status: IngestionItemStatus
    reason: str | None
    content_sha256: str | None
    duration_ms: int
    fetched: bool
    parsed: bool


@dataclass(frozen=True, slots=True)
class IngestionSummary:
    """Reconciled counts for one completed ingestion run."""

    run_id: UUID
    discovered_count: int
    fetched_count: int
    unchanged_count: int
    parsed_count: int
    invalid_count: int
    error_count: int
    outcomes: tuple[IngestionItemOutcome, ...]

    @property
    def ingested_count(self) -> int:
        """Return candidates inserted or updated with usable frontmatter."""
        return sum(outcome.status is IngestionItemStatus.INGESTED for outcome in self.outcomes)

    @property
    def skipped_count(self) -> int:
        """Return candidates excluded by an explicit safe policy."""
        return sum(outcome.status is IngestionItemStatus.SKIPPED for outcome in self.outcomes)

    def reconcile(self) -> None:
        """Raise if run-level counters do not match item-level evidence."""
        if self.discovered_count != len(self.outcomes):
            raise RuntimeError("discovered count does not match ingestion item outcomes")
        if self.fetched_count != sum(outcome.fetched for outcome in self.outcomes):
            raise RuntimeError("fetched count does not match ingestion item outcomes")
        if self.unchanged_count != sum(
            outcome.status is IngestionItemStatus.UNCHANGED for outcome in self.outcomes
        ):
            raise RuntimeError("unchanged count does not match ingestion item outcomes")
        if self.parsed_count != sum(outcome.parsed for outcome in self.outcomes):
            raise RuntimeError("parsed count does not match ingestion item outcomes")
        if self.invalid_count != sum(
            outcome.status is IngestionItemStatus.INVALID for outcome in self.outcomes
        ):
            raise RuntimeError("invalid count does not match ingestion item outcomes")
        if self.error_count != sum(
            outcome.status is IngestionItemStatus.ERROR for outcome in self.outcomes
        ):
            raise RuntimeError("error count does not match ingestion item outcomes")


class CandidateChangedError(RuntimeError):
    """GitHub contents no longer match the immutable candidate identity."""


class PrivateRepositoryError(RuntimeError):
    """A repository became private after public candidate discovery."""


async def run_ingestion(
    client: IngestionClient,
    session_factory: SessionFactory,
    manifest: CandidateManifest,
    *,
    manifest_path: Path,
    git_commit_sha: str,
    parser: SkillParser | None = None,
) -> IngestionSummary:
    """Ingest every candidate deterministically and continue after item failures."""
    serialized_manifest = serialize_candidate_manifest(manifest)
    normalized_commit = _validate_git_commit(git_commit_sha)
    normalized_manifest_path = _validate_manifest_path(manifest_path)
    parser = parser or SkillParser()

    start_rate_limits = await client.get_rate_limits()
    run_id = _create_run(
        session_factory,
        manifest,
        manifest_path=normalized_manifest_path,
        git_commit_sha=normalized_commit,
        manifest_sha256=hashlib.sha256(serialized_manifest).hexdigest(),
        rate_limit_start=_rate_limit_json(start_rate_limits),
    )
    repository_cache: dict[int, RepositoryContext] = {}
    outcomes: list[IngestionItemOutcome] = []

    try:
        for candidate_record in manifest.candidates:
            candidate = SkillCandidate(
                repository_id=candidate_record.repository_id,
                repository_full_name=candidate_record.repository_full_name,
                repository_html_url=candidate_record.repository_html_url,
                path=candidate_record.path,
                git_blob_sha=candidate_record.git_blob_sha,
                html_url=candidate_record.html_url,
                matched_queries=candidate_record.matched_queries,
            )
            outcome = await _ingest_candidate(
                client,
                session_factory,
                run_id,
                candidate,
                repository_cache,
                parser,
            )
            outcomes.append(outcome)

        end_rate_limits = await client.get_rate_limits()
        summary = _build_summary(run_id, outcomes)
        summary.reconcile()
        _complete_run(
            session_factory,
            summary,
            rate_limit_end=_rate_limit_json(end_rate_limits),
        )
        return summary
    except BaseException:
        _fail_run(session_factory, run_id)
        raise


async def _ingest_candidate(
    client: IngestionClient,
    session_factory: SessionFactory,
    run_id: UUID,
    candidate: SkillCandidate,
    repository_cache: dict[int, RepositoryContext],
    parser: SkillParser,
) -> IngestionItemOutcome:
    started_at = perf_counter()
    fetched = False
    parsed_content = False
    content_sha256: str | None = None

    try:
        repository = repository_cache.get(candidate.repository_id)
        if repository is None:
            repository = await _fetch_and_store_repository(
                client,
                session_factory,
                candidate,
            )
            repository_cache[candidate.repository_id] = repository

        existing = _find_existing(session_factory, repository, candidate.path)
        if existing is not None and existing.git_blob_sha == candidate.git_blob_sha:
            outcome = _outcome(
                candidate,
                status=IngestionItemStatus.UNCHANGED,
                reason=None,
                content_sha256=existing.content_sha256,
                started_at=started_at,
                fetched=False,
                parsed=False,
            )
            _store_unchanged(session_factory, run_id, existing, outcome)
            return outcome

        file_response = await client.get_file(
            repository.owner,
            repository.name,
            candidate.path,
            repository.default_branch,
        )
        if isinstance(file_response, GitHubNotModifiedResponse):
            raise CandidateChangedError("unexpected conditional response without a saved ETag")
        fetched = True
        _validate_file_identity(candidate, file_response.data)
        content = file_response.data.decode_content()
        content_sha256 = hashlib.sha256(content).hexdigest()

        directory_path = _candidate_directory(candidate.path)
        directory_response = await client.list_directory(
            repository.owner,
            repository.name,
            directory_path,
            repository.default_branch,
        )
        directory_entries = _parser_directory_entries(
            candidate,
            directory_response.data,
        )
        parsed = parser.parse(
            SkillSource(
                path=candidate.path,
                content=content,
                directory_entries=directory_entries,
            )
        )
        parsed_content = True

        if parsed.frontmatter is None:
            outcome = _outcome(
                candidate,
                status=IngestionItemStatus.INVALID,
                reason=_validation_reason(parsed),
                content_sha256=content_sha256,
                started_at=started_at,
                fetched=fetched,
                parsed=True,
            )
            _store_item(session_factory, run_id, outcome)
            return outcome

        status = (
            IngestionItemStatus.INVALID
            if parsed.validation_status is ValidationStatus.INVALID
            else IngestionItemStatus.INGESTED
        )
        outcome = _outcome(
            candidate,
            status=status,
            reason=_validation_reason(parsed) if status is IngestionItemStatus.INVALID else None,
            content_sha256=content_sha256,
            started_at=started_at,
            fetched=fetched,
            parsed=True,
        )
        _store_parsed(
            session_factory,
            run_id,
            repository,
            candidate,
            parsed,
            outcome,
        )
        return outcome
    except Exception as error:
        category, message, correlation_id, status = _classify_failure(error)
        outcome = _outcome(
            candidate,
            status=status,
            reason=_safe_reason(category, message, correlation_id=correlation_id),
            content_sha256=content_sha256,
            started_at=started_at,
            fetched=fetched,
            parsed=parsed_content,
        )
        _store_item(session_factory, run_id, outcome)
        return outcome


async def _fetch_and_store_repository(
    client: IngestionClient,
    session_factory: SessionFactory,
    candidate: SkillCandidate,
) -> RepositoryContext:
    owner, repository_name = candidate.repository_full_name.split("/", maxsplit=1)
    response = await client.get_repository(owner, repository_name)
    payload = response.data
    if payload.private:
        raise PrivateRepositoryError("repository became private after discovery")
    if payload.id != candidate.repository_id:
        raise CandidateChangedError("repository ID no longer matches the candidate manifest")
    if payload.full_name.casefold() != candidate.repository_full_name.casefold():
        raise CandidateChangedError("repository name no longer matches the candidate manifest")

    with session_factory() as session, session.begin():
        return upsert_repository(session, payload, etag=response.etag)


def _find_existing(
    session_factory: SessionFactory,
    repository: RepositoryContext,
    path: str,
) -> ExistingSkill | None:
    with session_factory() as session:
        return find_existing_skill(session, repository.database_id, path)


def _store_unchanged(
    session_factory: SessionFactory,
    run_id: UUID,
    existing: ExistingSkill,
    outcome: IngestionItemOutcome,
) -> None:
    with session_factory() as session, session.begin():
        mark_skill_seen(session, existing.database_id)
        _add_run_item(session, run_id, outcome)


def _store_parsed(
    session_factory: SessionFactory,
    run_id: UUID,
    repository: RepositoryContext,
    candidate: SkillCandidate,
    parsed: ParsedSkill,
    outcome: IngestionItemOutcome,
) -> None:
    assert outcome.content_sha256 is not None
    with session_factory() as session, session.begin():
        upsert_skill(
            session,
            repository,
            candidate,
            parsed,
            content_sha256=outcome.content_sha256,
        )
        _add_run_item(session, run_id, outcome)


def _store_item(
    session_factory: SessionFactory,
    run_id: UUID,
    outcome: IngestionItemOutcome,
) -> None:
    with session_factory() as session, session.begin():
        _add_run_item(session, run_id, outcome)


def _add_run_item(session: Session, run_id: UUID, outcome: IngestionItemOutcome) -> None:
    session.add(
        IngestionRunItem(
            ingestion_run_id=run_id,
            repository_full_name=outcome.repository_full_name,
            path=outcome.path,
            status=outcome.status,
            reason=outcome.reason,
            content_sha256=outcome.content_sha256,
            duration_ms=outcome.duration_ms,
        )
    )
    session.flush()


def _create_run(
    session_factory: SessionFactory,
    manifest: CandidateManifest,
    *,
    manifest_path: str,
    git_commit_sha: str,
    manifest_sha256: str,
    rate_limit_start: dict[str, object],
) -> UUID:
    with session_factory() as session, session.begin():
        run = IngestionRun(
            status=IngestionRunStatus.RUNNING,
            discovery_queries_json=list(manifest.header.queries),
            config_json={
                "candidate_manifest_schema": manifest.header.schema_version,
                "candidate_manifest_sha256": manifest_sha256,
                "target_skills": manifest.header.target_skills,
            },
            git_commit_sha=git_commit_sha,
            discovered_count=manifest.header.candidate_count,
            rate_limit_start_json=rate_limit_start,
            manifest_path=manifest_path,
        )
        session.add(run)
        session.flush()
        return run.id


def _complete_run(
    session_factory: SessionFactory,
    summary: IngestionSummary,
    *,
    rate_limit_end: dict[str, object],
) -> None:
    with session_factory() as session, session.begin():
        run = session.get(IngestionRun, summary.run_id)
        if run is None:
            raise RuntimeError("ingestion run disappeared before completion")
        run.status = IngestionRunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.fetched_count = summary.fetched_count
        run.unchanged_count = summary.unchanged_count
        run.parsed_count = summary.parsed_count
        run.invalid_count = summary.invalid_count
        run.error_count = summary.error_count
        run.rate_limit_end_json = rate_limit_end


def _fail_run(session_factory: SessionFactory, run_id: UUID) -> None:
    try:
        with session_factory() as session, session.begin():
            run = session.get(IngestionRun, run_id)
            if run is not None:
                run.status = IngestionRunStatus.FAILED
                run.completed_at = datetime.now(UTC)
    except SQLAlchemyError:
        return


def _build_summary(run_id: UUID, outcomes: list[IngestionItemOutcome]) -> IngestionSummary:
    frozen_outcomes = tuple(outcomes)
    return IngestionSummary(
        run_id=run_id,
        discovered_count=len(frozen_outcomes),
        fetched_count=sum(outcome.fetched for outcome in frozen_outcomes),
        unchanged_count=sum(
            outcome.status is IngestionItemStatus.UNCHANGED for outcome in frozen_outcomes
        ),
        parsed_count=sum(outcome.parsed for outcome in frozen_outcomes),
        invalid_count=sum(
            outcome.status is IngestionItemStatus.INVALID for outcome in frozen_outcomes
        ),
        error_count=sum(outcome.status is IngestionItemStatus.ERROR for outcome in frozen_outcomes),
        outcomes=frozen_outcomes,
    )


def _outcome(
    candidate: SkillCandidate,
    *,
    status: IngestionItemStatus,
    reason: str | None,
    content_sha256: str | None,
    started_at: float,
    fetched: bool,
    parsed: bool,
) -> IngestionItemOutcome:
    return IngestionItemOutcome(
        repository_full_name=candidate.repository_full_name,
        path=candidate.path,
        status=status,
        reason=reason,
        content_sha256=content_sha256,
        duration_ms=max(0, int((perf_counter() - started_at) * 1_000)),
        fetched=fetched,
        parsed=parsed,
    )


def _validate_file_identity(candidate: SkillCandidate, payload: GitHubFilePayload) -> None:
    if payload.path != candidate.path or payload.sha != candidate.git_blob_sha:
        raise CandidateChangedError("file identity changed after candidate discovery")


def _candidate_directory(path: str) -> str:
    parent = PurePosixPath(path).parent
    return "" if parent == PurePosixPath(".") else parent.as_posix()


def _parser_directory_entries(
    candidate: SkillCandidate,
    entries: tuple[GitHubDirectoryEntryPayload, ...],
) -> tuple[SkillDirectoryEntry, ...]:
    parent = PurePosixPath(candidate.path).parent
    parsed_entries: list[SkillDirectoryEntry] = []
    for entry in entries:
        try:
            relative_path = PurePosixPath(entry.path).relative_to(parent).as_posix()
        except ValueError:
            raise CandidateChangedError(
                "directory response contained an entry outside the skill directory"
            ) from None
        if relative_path in {"", "."}:
            raise CandidateChangedError("directory response contained an empty relative path")
        if entry.type not in {"file", "dir"}:
            continue
        parsed_entries.append(
            SkillDirectoryEntry(
                relative_path=relative_path,
                kind=(
                    DirectoryEntryKind.FILE
                    if entry.type == "file"
                    else DirectoryEntryKind.DIRECTORY
                ),
                size_bytes=entry.size,
                git_blob_sha=entry.sha,
            )
        )
    return tuple(parsed_entries)


def _validation_reason(parsed: ParsedSkill) -> str:
    codes = sorted({message.code for message in parsed.validation_messages})
    return json.dumps(
        {
            "category": IngestionFailureCategory.VALIDATION.value,
            "codes": codes,
            "message": "Parser reported invalid skill content.",
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _classify_failure(
    error: BaseException,
) -> tuple[IngestionFailureCategory, str, str | None, IngestionItemStatus]:
    if isinstance(error, PrivateRepositoryError):
        return (
            IngestionFailureCategory.PRIVATE_REPOSITORY,
            "Repository is no longer public; candidate was skipped.",
            None,
            IngestionItemStatus.SKIPPED,
        )
    if isinstance(error, CandidateChangedError):
        return (
            IngestionFailureCategory.CANDIDATE_CHANGED,
            "GitHub metadata changed after discovery; rerun discovery before retrying.",
            None,
            IngestionItemStatus.ERROR,
        )
    github_categories: tuple[tuple[type[GitHubClientError], IngestionFailureCategory, str], ...] = (
        (
            GitHubAuthenticationError,
            IngestionFailureCategory.AUTHENTICATION,
            "GitHub rejected the configured credential.",
        ),
        (
            GitHubPermissionError,
            IngestionFailureCategory.PERMISSION,
            "GitHub denied access to the requested public resource.",
        ),
        (
            GitHubNotFoundError,
            IngestionFailureCategory.NOT_FOUND,
            "GitHub resource was not found.",
        ),
        (
            GitHubRateLimitError,
            IngestionFailureCategory.RATE_LIMIT,
            "GitHub rate limits prevented this candidate from completing.",
        ),
        (
            GitHubPayloadTooLargeError,
            IngestionFailureCategory.PAYLOAD_TOO_LARGE,
            "GitHub content exceeded an ingestion safety limit.",
        ),
        (
            GitHubPayloadError,
            IngestionFailureCategory.PAYLOAD,
            "GitHub returned content outside the validated API contract.",
        ),
        (
            GitHubTransportError,
            IngestionFailureCategory.TRANSPORT,
            "GitHub transport retries were exhausted.",
        ),
        (
            GitHubClientError,
            IngestionFailureCategory.PAYLOAD,
            "GitHub request failed safely.",
        ),
    )
    for error_type, category, message in github_categories:
        if isinstance(error, error_type):
            return category, message, error.correlation_id, IngestionItemStatus.ERROR
    if isinstance(error, (PersistenceConflictError, SQLAlchemyError)):
        return (
            IngestionFailureCategory.PERSISTENCE,
            "Database persistence rejected conflicting or invalid state.",
            None,
            IngestionItemStatus.ERROR,
        )
    return (
        IngestionFailureCategory.UNEXPECTED,
        "Candidate failed with an unexpected internal error.",
        None,
        IngestionItemStatus.ERROR,
    )


def _safe_reason(
    category: IngestionFailureCategory,
    message: str,
    *,
    correlation_id: str | None,
) -> str:
    payload = {"category": category.value, "message": message}
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    return json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )


def _rate_limit_json(
    response: GitHubResponse[GitHubRateLimitResponsePayload],
) -> dict[str, object]:
    return response.data.model_dump(mode="json")


def _validate_git_commit(value: str) -> str:
    normalized = value.strip().lower()
    if _GIT_COMMIT_RE.fullmatch(normalized) is None:
        raise ValueError("git_commit_sha must be a full lowercase hexadecimal commit ID")
    return normalized


def _validate_manifest_path(path: Path) -> str:
    if path.is_absolute() or path.suffix != ".jsonl" or ".." in path.parts:
        raise ValueError("manifest_path must be a safe relative JSONL path")
    normalized = path.as_posix()
    if not normalized or normalized.startswith("./"):
        raise ValueError("manifest_path must be normalized")
    return normalized
