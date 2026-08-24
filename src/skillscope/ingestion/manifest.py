"""Versioned, deterministic candidate manifests for GitHub discovery runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_serializer,
    model_validator,
)

from skillscope.ingestion.discovery import (
    MAX_DISCOVERY_PAGES_PER_QUERY,
    MAX_DISCOVERY_QUERIES,
    MAX_DISCOVERY_TARGET,
    DiscoveryResult,
    normalize_seed_repositories,
)
from skillscope.ingestion.models import (
    GitHubHtmlUrl,
    GitHubRelativePath,
    GitHubRepositoryFullName,
    GitObjectSha,
)

MANIFEST_SCHEMA_VERSION: Literal[1] = 1
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_MANIFEST_RECORD_BYTES = 1024 * 1024
MAX_MANIFEST_RECORDS = (
    1 + MAX_DISCOVERY_QUERIES * MAX_DISCOVERY_PAGES_PER_QUERY + MAX_DISCOVERY_TARGET
)
GitCommit = Annotated[
    str,
    Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]


class ManifestValidationError(ValueError):
    """A candidate manifest violated its versioned contract."""


class ManifestRecord(BaseModel):
    """Immutable base for strict JSONL records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidateManifestHeader(ManifestRecord):
    """Run-level metadata stored as the first JSONL record."""

    record_type: Literal["manifest"] = "manifest"
    schema_version: Literal[1] = MANIFEST_SCHEMA_VERSION
    generated_at: datetime
    git_commit: GitCommit
    target_skills: int = Field(ge=1, le=MAX_DISCOVERY_TARGET)
    target_reached: bool
    candidate_count: int = Field(ge=0, le=MAX_DISCOVERY_TARGET)
    page_count: int = Field(
        ge=0,
        le=MAX_DISCOVERY_QUERIES * MAX_DISCOVERY_PAGES_PER_QUERY,
    )
    seed_repositories: tuple[str, ...] = Field(min_length=1)
    queries: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_DISCOVERY_QUERIES,
    )

    @model_validator(mode="after")
    def validate_run_metadata(self) -> CandidateManifestHeader:
        """Require canonical inputs and internally consistent target counts."""
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        if normalize_seed_repositories(self.seed_repositories) != self.seed_repositories:
            raise ValueError("seed repositories must be normalized and sorted")
        if len(set(self.queries)) != len(self.queries):
            raise ValueError("manifest queries must be unique")
        if any(not query or query != query.strip() for query in self.queries):
            raise ValueError("manifest queries must be non-empty and trimmed")
        if self.target_reached and self.candidate_count != self.target_skills:
            raise ValueError("a reached target must contain exactly target_skills candidates")
        if not self.target_reached and self.candidate_count >= self.target_skills:
            raise ValueError("an unreached target must contain fewer than target_skills candidates")
        return self

    @field_serializer("generated_at")
    def serialize_generated_at(self, value: datetime) -> str:
        """Render timestamps in one canonical UTC representation."""
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class CandidateManifestPage(ManifestRecord):
    """Evidence describing one consumed GitHub code-search page."""

    record_type: Literal["page"] = "page"
    query: str = Field(min_length=1)
    page_number: int = Field(ge=1, le=MAX_DISCOVERY_PAGES_PER_QUERY)
    item_count: int = Field(ge=0, le=100)
    accepted_item_count: int = Field(ge=0, le=100)
    total_count: int = Field(ge=0)
    incomplete_results: bool
    has_next: bool
    first_result: str | None = Field(default=None, min_length=1)
    last_result: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_page_boundary(self) -> CandidateManifestPage:
        """Ensure counts and boundary identifiers describe the same page."""
        if self.accepted_item_count > self.item_count:
            raise ValueError("accepted_item_count cannot exceed item_count")
        if self.total_count < self.item_count:
            raise ValueError("total_count cannot be smaller than item_count")
        boundaries = (self.first_result, self.last_result)
        if self.item_count == 0 and boundaries != (None, None):
            raise ValueError("an empty page cannot have result boundaries")
        if self.item_count > 0 and None in boundaries:
            raise ValueError("a non-empty page requires both result boundaries")
        return self


class CandidateManifestCandidate(ManifestRecord):
    """One body-free public ``SKILL.md`` candidate record."""

    record_type: Literal["candidate"] = "candidate"
    repository_id: int = Field(gt=0)
    repository_full_name: GitHubRepositoryFullName
    repository_html_url: GitHubHtmlUrl
    path: GitHubRelativePath
    git_blob_sha: GitObjectSha
    html_url: GitHubHtmlUrl
    matched_queries: tuple[str, ...] = Field(
        min_length=1,
        max_length=MAX_DISCOVERY_QUERIES,
    )

    @property
    def identity(self) -> tuple[int, str]:
        """Return the manifest deduplication key."""
        return (self.repository_id, self.path)


type CandidateManifestRecord = Annotated[
    CandidateManifestHeader | CandidateManifestPage | CandidateManifestCandidate,
    Field(discriminator="record_type"),
]
_MANIFEST_RECORD_ADAPTER: TypeAdapter[CandidateManifestRecord] = TypeAdapter(
    CandidateManifestRecord
)


@dataclass(frozen=True, slots=True)
class CandidateManifest:
    """A validated manifest document in canonical record order."""

    header: CandidateManifestHeader
    pages: tuple[CandidateManifestPage, ...]
    candidates: tuple[CandidateManifestCandidate, ...]


def build_candidate_manifest(
    result: DiscoveryResult,
    *,
    generated_at: datetime,
    git_commit: str,
) -> CandidateManifest:
    """Convert a discovery result into strict, body-free manifest records."""
    try:
        normalized_generated_at = _normalize_timestamp(generated_at)
        header = CandidateManifestHeader(
            generated_at=normalized_generated_at,
            git_commit=git_commit.strip().lower(),
            target_skills=result.target_skills,
            target_reached=result.target_reached,
            candidate_count=len(result.candidates),
            page_count=len(result.pages),
            seed_repositories=result.plan.seed_repositories,
            queries=result.plan.queries,
        )
        pages = tuple(
            CandidateManifestPage(
                query=page.query,
                page_number=page.page_number,
                item_count=page.item_count,
                accepted_item_count=page.accepted_item_count,
                total_count=page.total_count,
                incomplete_results=page.incomplete_results,
                has_next=page.has_next,
                first_result=page.first_result,
                last_result=page.last_result,
            )
            for page in result.pages
        )
        candidates = tuple(
            CandidateManifestCandidate(
                repository_id=candidate.repository_id,
                repository_full_name=candidate.repository_full_name,
                repository_html_url=candidate.repository_html_url,
                path=candidate.path,
                git_blob_sha=candidate.git_blob_sha,
                html_url=candidate.html_url,
                matched_queries=candidate.matched_queries,
            )
            for candidate in result.candidates
        )
        manifest = CandidateManifest(
            header=header,
            pages=pages,
            candidates=candidates,
        )
        _validate_manifest_document(manifest)
        return manifest
    except (ValidationError, ValueError) as error:
        if isinstance(error, ManifestValidationError):
            raise
        raise ManifestValidationError("discovery result could not form a valid manifest") from error


def serialize_candidate_manifest(manifest: CandidateManifest) -> bytes:
    """Return canonical UTF-8 JSONL with a required final newline."""
    _validate_manifest_document(manifest)
    records: list[ManifestRecord] = [manifest.header]
    records.extend(manifest.pages)
    records.extend(manifest.candidates)
    lines = (
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in records
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_candidate_manifest(path: Path, manifest: CandidateManifest) -> None:
    """Atomically replace a JSONL manifest after complete serialization."""
    if path.suffix != ".jsonl":
        raise ValueError("candidate manifest path must end with .jsonl")
    serialized = serialize_candidate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        assert temporary_path is not None
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def read_candidate_manifest(path: Path) -> CandidateManifest:
    """Read and validate one bounded, canonical-order manifest document."""
    serialized = path.read_bytes()
    if not serialized:
        raise ManifestValidationError("candidate manifest is empty")
    if len(serialized) > MAX_MANIFEST_BYTES:
        raise ManifestValidationError(
            f"candidate manifest exceeds the {MAX_MANIFEST_BYTES}-byte safety limit"
        )
    if not serialized.endswith(b"\n"):
        raise ManifestValidationError("candidate manifest must end with a newline")

    lines = serialized.splitlines()
    if len(lines) > MAX_MANIFEST_RECORDS:
        raise ManifestValidationError(
            f"candidate manifest exceeds the {MAX_MANIFEST_RECORDS}-record safety limit"
        )

    records: list[CandidateManifestRecord] = []
    for line in lines:
        if not line:
            raise ManifestValidationError("candidate manifest cannot contain blank records")
        if len(line) > MAX_MANIFEST_RECORD_BYTES:
            raise ManifestValidationError(
                "candidate manifest record exceeds the per-record safety limit"
            )
        try:
            records.append(_MANIFEST_RECORD_ADAPTER.validate_json(line))
        except ValidationError as error:
            raise ManifestValidationError(
                "candidate manifest contains an invalid record"
            ) from error

    first_record, *remaining_records = records
    if not isinstance(first_record, CandidateManifestHeader):
        raise ManifestValidationError("candidate manifest must start with its header")

    pages: list[CandidateManifestPage] = []
    candidates: list[CandidateManifestCandidate] = []
    candidate_records_started = False
    for record in remaining_records:
        if isinstance(record, CandidateManifestHeader):
            raise ManifestValidationError("candidate manifest contains multiple headers")
        if isinstance(record, CandidateManifestPage):
            if candidate_records_started:
                raise ManifestValidationError("page records cannot appear after candidate records")
            pages.append(record)
            continue
        if not isinstance(record, CandidateManifestCandidate):
            raise ManifestValidationError("candidate manifest contains an unknown record")
        candidate_records_started = True
        candidates.append(record)

    manifest = CandidateManifest(
        header=first_record,
        pages=tuple(pages),
        candidates=tuple(candidates),
    )
    _validate_manifest_document(manifest)
    return manifest


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ManifestValidationError("generated_at must include a timezone")
    return value.astimezone(UTC)


def _validate_manifest_document(manifest: CandidateManifest) -> None:
    header = manifest.header
    if header.page_count != len(manifest.pages):
        raise ManifestValidationError("manifest page_count does not match its records")
    if header.candidate_count != len(manifest.candidates):
        raise ManifestValidationError("manifest candidate_count does not match its records")

    query_rank = {query: index for index, query in enumerate(header.queries)}
    expected_page_numbers: dict[str, int] = {}
    previous_page_key: tuple[int, int] | None = None
    for page in manifest.pages:
        if page.query not in query_rank:
            raise ManifestValidationError("page record references an unknown query")
        expected_page_number = expected_page_numbers.get(page.query, 1)
        if page.page_number != expected_page_number:
            raise ManifestValidationError("page numbers must be contiguous within each query")
        expected_page_numbers[page.query] = expected_page_number + 1
        page_key = (query_rank[page.query], page.page_number)
        if previous_page_key is not None and page_key <= previous_page_key:
            raise ManifestValidationError("page records must follow manifest query order")
        previous_page_key = page_key

    identities: set[tuple[int, str]] = set()
    previous_candidate_key: tuple[str, str] | None = None
    for candidate in manifest.candidates:
        if candidate.identity in identities:
            raise ManifestValidationError("manifest contains duplicate candidates")
        identities.add(candidate.identity)
        candidate_key = (candidate.repository_full_name, candidate.path)
        if previous_candidate_key is not None and candidate_key <= previous_candidate_key:
            raise ManifestValidationError(
                "candidate records must be uniquely and deterministically sorted"
            )
        previous_candidate_key = candidate_key
        if any(query not in query_rank for query in candidate.matched_queries):
            raise ManifestValidationError("candidate record references an unknown query")
        matched_query_ranks = tuple(query_rank[query] for query in candidate.matched_queries)
        if matched_query_ranks != tuple(sorted(set(matched_query_ranks))):
            raise ManifestValidationError(
                "candidate matched_queries must be unique and follow query order"
            )
