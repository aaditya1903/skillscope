"""Canonical, body-free manifests for frozen ingestion snapshots."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    ValidationError,
    field_serializer,
    model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from skillscope.db.enums import IngestionItemStatus, IngestionRunStatus, ValidationStatus
from skillscope.db.models import IngestionRun, IngestionRunItem, Repository, Skill
from skillscope.ingestion.manifest import (
    CandidateManifest,
    serialize_candidate_manifest,
)
from skillscope.ingestion.models import (
    GitHubRelativePath,
    GitHubRepositoryFullName,
    GitObjectSha,
)

SNAPSHOT_SCHEMA_VERSION: Literal[1] = 1
MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_RECORD_BYTES = 1024 * 1024
MAX_SNAPSHOT_ITEMS = 1_000
GitCommit = Annotated[str, Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
_FAILURE_ADAPTER: TypeAdapter[dict[str, JsonValue]] = TypeAdapter(dict[str, JsonValue])


class SnapshotValidationError(ValueError):
    """A dataset snapshot violated its body-free evidence contract."""


class SnapshotRecord(BaseModel):
    """Strict immutable base for snapshot JSONL records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DatasetSnapshotHeader(SnapshotRecord):
    """Run and count evidence stored as the first snapshot record."""

    record_type: Literal["snapshot"] = "snapshot"
    schema_version: Literal[1] = SNAPSHOT_SCHEMA_VERSION
    generated_at: datetime
    git_commit: GitCommit
    ingestion_run_id: UUID
    candidate_manifest_path: str = Field(min_length=1)
    candidate_manifest_sha256: Sha256
    candidate_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    item_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    repository_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    stored_skill_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    ingested_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    unchanged_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    invalid_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    skipped_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    error_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    valid_skill_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    warning_skill_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)
    invalid_skill_count: int = Field(ge=0, le=MAX_SNAPSHOT_ITEMS)

    @model_validator(mode="after")
    def validate_counts(self) -> DatasetSnapshotHeader:
        """Require candidate, outcome, and stored-validation totals to reconcile."""
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        if self.candidate_count != self.item_count:
            raise ValueError("candidate_count must equal item_count")
        outcome_total = (
            self.ingested_count
            + self.unchanged_count
            + self.invalid_count
            + self.skipped_count
            + self.error_count
        )
        if outcome_total != self.item_count:
            raise ValueError("item statuses must sum to item_count")
        validation_total = (
            self.valid_skill_count + self.warning_skill_count + self.invalid_skill_count
        )
        if validation_total != self.stored_skill_count:
            raise ValueError("stored validation statuses must sum to stored_skill_count")
        if self.repository_count > self.stored_skill_count:
            raise ValueError("repository_count cannot exceed stored_skill_count")
        _validate_relative_jsonl_path(self.candidate_manifest_path)
        return self

    @field_serializer("generated_at")
    def serialize_generated_at(self, value: datetime) -> str:
        """Render one canonical UTC timestamp representation."""
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class DatasetSnapshotItem(SnapshotRecord):
    """One candidate outcome containing identifiers and hashes, never its body."""

    record_type: Literal["item"] = "item"
    repository_id: int = Field(gt=0)
    repository_full_name: GitHubRepositoryFullName
    path: GitHubRelativePath
    git_blob_sha: GitObjectSha
    status: IngestionItemStatus
    content_sha256: Sha256 | None = None
    stored: bool
    validation_status: ValidationStatus | None = None
    failure: dict[str, JsonValue] | None = None

    @property
    def identity(self) -> tuple[int, str]:
        """Return the upstream-stable candidate identity."""
        return (self.repository_id, self.path)

    @model_validator(mode="after")
    def validate_outcome(self) -> DatasetSnapshotItem:
        """Keep status, storage, validation, and failure evidence consistent."""
        successful = self.status in {
            IngestionItemStatus.INGESTED,
            IngestionItemStatus.UNCHANGED,
        }
        failed = self.status in {
            IngestionItemStatus.INVALID,
            IngestionItemStatus.SKIPPED,
            IngestionItemStatus.ERROR,
        }
        if successful and not self.stored:
            raise ValueError("ingested and unchanged items must be stored")
        if successful and self.failure is not None:
            raise ValueError("successful items cannot contain failure evidence")
        if failed and self.failure is None:
            raise ValueError("non-success items require failure evidence")
        if self.status in {IngestionItemStatus.SKIPPED, IngestionItemStatus.ERROR} and self.stored:
            raise ValueError("skipped and error items cannot enter the frozen snapshot")
        if self.stored and self.validation_status is None:
            raise ValueError("stored items require validation_status")
        if not self.stored and self.validation_status is not None:
            raise ValueError("unstored items cannot contain validation_status")
        if self.stored and self.content_sha256 is None:
            raise ValueError("stored items require content_sha256")
        return self


type DatasetSnapshotRecord = DatasetSnapshotHeader | DatasetSnapshotItem


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    """A validated snapshot document in deterministic candidate order."""

    header: DatasetSnapshotHeader
    items: tuple[DatasetSnapshotItem, ...]


def build_dataset_snapshot(
    session: Session,
    candidate_manifest: CandidateManifest,
    *,
    ingestion_run_id: UUID,
    candidate_manifest_path: Path,
    generated_at: datetime,
    git_commit: str,
) -> DatasetSnapshot:
    """Reconcile one completed run, its candidates, and current database rows."""
    serialized_candidate_manifest = serialize_candidate_manifest(candidate_manifest)
    manifest_path = _validate_relative_jsonl_path(candidate_manifest_path.as_posix())
    normalized_timestamp = _normalize_timestamp(generated_at)
    normalized_commit = git_commit.strip().lower()

    run = session.get(IngestionRun, ingestion_run_id)
    if run is None:
        raise SnapshotValidationError("ingestion run does not exist")
    if run.status is not IngestionRunStatus.COMPLETED:
        raise SnapshotValidationError("dataset snapshots require a completed ingestion run")
    if run.manifest_path != manifest_path:
        raise SnapshotValidationError("ingestion run references a different candidate manifest")

    run_items = session.scalars(
        select(IngestionRunItem)
        .where(IngestionRunItem.ingestion_run_id == ingestion_run_id)
        .order_by(IngestionRunItem.repository_full_name, IngestionRunItem.path)
    ).all()
    item_by_name_path = {(item.repository_full_name, item.path): item for item in run_items}
    if len(item_by_name_path) != len(run_items):
        raise SnapshotValidationError("ingestion run contains duplicate item identities")
    if len(run_items) != candidate_manifest.header.candidate_count:
        raise SnapshotValidationError("ingestion item count does not match candidate manifest")

    repository_ids = {candidate.repository_id for candidate in candidate_manifest.candidates}
    skill_rows = session.execute(
        select(Repository.github_repository_id, Skill)
        .join(Skill, Skill.repository_id == Repository.id)
        .where(Repository.github_repository_id.in_(repository_ids))
    ).all()
    skill_by_identity = {(repository_id, skill.path): skill for repository_id, skill in skill_rows}

    snapshot_items: list[DatasetSnapshotItem] = []
    stored_repository_ids: set[int] = set()
    for candidate in candidate_manifest.candidates:
        run_item = item_by_name_path.get((candidate.repository_full_name, candidate.path))
        if run_item is None:
            raise SnapshotValidationError("candidate is missing its ingestion item outcome")
        skill = skill_by_identity.get(candidate.identity)
        storable_status = run_item.status in {
            IngestionItemStatus.INGESTED,
            IngestionItemStatus.UNCHANGED,
            IngestionItemStatus.INVALID,
        }
        stored = bool(
            storable_status
            and skill is not None
            and skill.git_blob_sha == candidate.git_blob_sha
            and skill.content_sha256 == run_item.content_sha256
        )
        if stored:
            stored_repository_ids.add(candidate.repository_id)

        snapshot_items.append(
            DatasetSnapshotItem(
                repository_id=candidate.repository_id,
                repository_full_name=candidate.repository_full_name,
                path=candidate.path,
                git_blob_sha=candidate.git_blob_sha,
                status=run_item.status,
                content_sha256=run_item.content_sha256,
                stored=stored,
                validation_status=skill.validation_status if stored and skill is not None else None,
                failure=_parse_failure(run_item.reason),
            )
        )

    status_counts = Counter(item.status for item in snapshot_items)
    validation_counts = Counter(
        item.validation_status for item in snapshot_items if item.validation_status is not None
    )
    stored_skill_count = sum(item.stored for item in snapshot_items)
    header = DatasetSnapshotHeader(
        generated_at=normalized_timestamp,
        git_commit=normalized_commit,
        ingestion_run_id=ingestion_run_id,
        candidate_manifest_path=manifest_path,
        candidate_manifest_sha256=hashlib.sha256(serialized_candidate_manifest).hexdigest(),
        candidate_count=candidate_manifest.header.candidate_count,
        item_count=len(snapshot_items),
        repository_count=len(stored_repository_ids),
        stored_skill_count=stored_skill_count,
        ingested_count=status_counts[IngestionItemStatus.INGESTED],
        unchanged_count=status_counts[IngestionItemStatus.UNCHANGED],
        invalid_count=status_counts[IngestionItemStatus.INVALID],
        skipped_count=status_counts[IngestionItemStatus.SKIPPED],
        error_count=status_counts[IngestionItemStatus.ERROR],
        valid_skill_count=validation_counts[ValidationStatus.VALID],
        warning_skill_count=validation_counts[ValidationStatus.WARNING],
        invalid_skill_count=validation_counts[ValidationStatus.INVALID],
    )
    snapshot = DatasetSnapshot(header=header, items=tuple(snapshot_items))
    _validate_snapshot(snapshot)
    _validate_run_counts(run, header)
    return snapshot


def serialize_dataset_snapshot(snapshot: DatasetSnapshot) -> bytes:
    """Return canonical UTF-8 JSONL with a required final newline."""
    _validate_snapshot(snapshot)
    records: tuple[DatasetSnapshotRecord, ...] = (snapshot.header, *snapshot.items)
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


def write_dataset_snapshot(path: Path, snapshot: DatasetSnapshot) -> None:
    """Atomically replace a validated relative JSONL snapshot."""
    _validate_relative_jsonl_path(path.as_posix())
    serialized = serialize_dataset_snapshot(snapshot)
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


def read_dataset_snapshot(path: Path) -> DatasetSnapshot:
    """Read and strictly validate one bounded snapshot document."""
    serialized = path.read_bytes()
    if not serialized or len(serialized) > MAX_SNAPSHOT_BYTES:
        raise SnapshotValidationError("dataset snapshot is empty or exceeds its safety limit")
    if not serialized.endswith(b"\n"):
        raise SnapshotValidationError("dataset snapshot must end with a newline")
    lines = serialized.splitlines()
    if len(lines) > MAX_SNAPSHOT_ITEMS + 1:
        raise SnapshotValidationError("dataset snapshot exceeds its record limit")

    try:
        header = DatasetSnapshotHeader.model_validate_json(lines[0])
        items = tuple(DatasetSnapshotItem.model_validate_json(line) for line in lines[1:])
    except (IndexError, ValidationError) as error:
        raise SnapshotValidationError("dataset snapshot contains an invalid record") from error
    if any(not line or len(line) > MAX_SNAPSHOT_RECORD_BYTES for line in lines):
        raise SnapshotValidationError("dataset snapshot contains an invalid record boundary")
    snapshot = DatasetSnapshot(header=header, items=items)
    _validate_snapshot(snapshot)
    if serialize_dataset_snapshot(snapshot) != serialized:
        raise SnapshotValidationError("dataset snapshot is not canonically serialized")
    return snapshot


def _validate_snapshot(snapshot: DatasetSnapshot) -> None:
    if snapshot.header.item_count != len(snapshot.items):
        raise SnapshotValidationError("snapshot item_count does not match its records")
    identities: set[tuple[int, str]] = set()
    previous_key: tuple[str, str] | None = None
    for item in snapshot.items:
        if item.identity in identities:
            raise SnapshotValidationError("dataset snapshot contains duplicate candidates")
        identities.add(item.identity)
        key = (item.repository_full_name, item.path)
        if previous_key is not None and key <= previous_key:
            raise SnapshotValidationError("snapshot items must be deterministically sorted")
        previous_key = key


def _validate_run_counts(run: IngestionRun, header: DatasetSnapshotHeader) -> None:
    expected = (
        header.candidate_count,
        header.unchanged_count,
        header.invalid_count,
        header.error_count,
    )
    actual = (
        run.discovered_count,
        run.unchanged_count,
        run.invalid_count,
        run.error_count,
    )
    if actual != expected:
        raise SnapshotValidationError("ingestion run counters do not match snapshot outcomes")


def _parse_failure(reason: str | None) -> dict[str, JsonValue] | None:
    if reason is None:
        return None
    try:
        raw_failure = json.loads(reason)
        failure = _FAILURE_ADAPTER.validate_python(raw_failure, strict=True)
    except (json.JSONDecodeError, ValidationError) as error:
        raise SnapshotValidationError(
            "ingestion item reason is not safe structured JSON"
        ) from error
    if "category" not in failure or "message" not in failure:
        raise SnapshotValidationError("ingestion item failure is missing safe fields")
    return failure


def _normalize_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise SnapshotValidationError("generated_at must include a timezone")
    return value.astimezone(UTC)


def _validate_relative_jsonl_path(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or path.suffix != ".jsonl" or ".." in path.parts:
        raise SnapshotValidationError("snapshot paths must be safe relative JSONL paths")
    normalized = path.as_posix()
    if not normalized or normalized.startswith("./"):
        raise SnapshotValidationError("snapshot paths must be normalized")
    return normalized
