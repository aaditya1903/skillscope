"""Frozen, integrity-checked corpus construction for retrieval baselines."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from skillscope.db.enums import LicenseStatus, ValidationStatus
from skillscope.db.models import Repository, Skill
from skillscope.ingestion.snapshot import DatasetSnapshotItem, read_dataset_snapshot
from skillscope.retrieval.config import BM25BaselineConfig
from skillscope.retrieval.text import normalize_lexical_text, partition_markdown_body, tokenize


class CorpusIntegrityError(ValueError):
    """Frozen snapshot records and current database rows do not reconcile."""


class StaleCorpusError(CorpusIntegrityError):
    """Configured or referenced corpus bytes have changed."""


@dataclass(frozen=True, slots=True)
class LexicalFields:
    """Separately constructed fields retained for later retrieval experiments."""

    name_text: str
    description_text: str
    metadata_text: str
    heading_text: str
    body_text: str

    @property
    def combined_text(self) -> str:
        """Return the ordinary unweighted BM25 document."""

        return " ".join(
            field
            for field in (
                self.name_text,
                self.description_text,
                self.metadata_text,
                self.heading_text,
                self.body_text,
            )
            if field
        )


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    """One retrieval-eligible skill and its deterministic lexical document."""

    document_id: str
    skill_id: UUID
    repository_id: int
    repository_full_name: str
    path: str
    name: str
    safe_snippet: str
    validation_status: ValidationStatus
    content_sha256: str
    fields: LexicalFields
    tokens: tuple[str, ...]
    license_status: LicenseStatus = LicenseStatus.UNKNOWN
    has_scripts: bool = False

    @property
    def embedding_text(self) -> str:
        """Return the labelled, versioned dense-retrieval input text."""

        return "\n".join(
            (
                f"name: {self.fields.name_text}",
                f"description: {self.fields.description_text}",
                f"metadata: {self.fields.metadata_text}",
                f"headings: {self.fields.heading_text}",
                f"body: {self.fields.body_text}",
            )
        )

    @property
    def embedding_text_sha256(self) -> str:
        """Bind stored embeddings to the exact UTF-8 model input."""

        return hashlib.sha256(self.embedding_text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class FrozenCorpus:
    """Documents tied to the exact canonical dataset-snapshot bytes."""

    snapshot_path: str
    snapshot_sha256: str
    documents: tuple[CorpusDocument, ...]


def load_frozen_corpus(
    session: Session,
    config: BM25BaselineConfig,
    *,
    snapshot_path: Path | None = None,
) -> FrozenCorpus:
    """Load valid and warning skills after snapshot and database reconciliation."""

    resolved_snapshot_path = snapshot_path or Path(config.corpus_snapshot_path)
    snapshot_bytes = _read_bytes(resolved_snapshot_path, "dataset snapshot")
    snapshot_sha256 = hashlib.sha256(snapshot_bytes).hexdigest()
    if snapshot_sha256 != config.corpus_snapshot_sha256:
        raise StaleCorpusError(
            "dataset snapshot SHA-256 does not match the saved BM25 baseline configuration"
        )

    snapshot = read_dataset_snapshot(resolved_snapshot_path)
    candidate_path = Path(snapshot.header.candidate_manifest_path)
    candidate_bytes = _read_bytes(candidate_path, "candidate manifest")
    candidate_sha256 = hashlib.sha256(candidate_bytes).hexdigest()
    if candidate_sha256 != snapshot.header.candidate_manifest_sha256:
        raise StaleCorpusError("candidate manifest SHA-256 does not match the dataset snapshot")

    eligible_items = tuple(
        item
        for item in snapshot.items
        if item.stored
        and item.validation_status in {ValidationStatus.VALID, ValidationStatus.WARNING}
    )
    if not eligible_items:
        raise CorpusIntegrityError("frozen snapshot has no retrieval-eligible skills")

    expected_by_identity = {item.identity: item for item in eligible_items}
    if len(expected_by_identity) != len(eligible_items):
        raise CorpusIntegrityError("frozen snapshot contains duplicate eligible identities")

    repository_ids = {repository_id for repository_id, _ in expected_by_identity}
    statement = (
        select(
            Repository.github_repository_id,
            Repository.full_name,
            Repository.license_status,
            Skill.id,
            Skill.path,
            Skill.content_sha256,
            Skill.name,
            Skill.description,
            Skill.declared_license,
            Skill.compatibility,
            Skill.allowed_tools,
            Skill.metadata_json,
            Skill.body_text,
            Skill.safe_snippet,
            Skill.validation_status,
            Skill.has_scripts,
        )
        .join(Skill, Skill.repository_id == Repository.id)
        .where(Repository.github_repository_id.in_(repository_ids))
    )
    rows = session.execute(statement).tuples().all()
    row_by_identity = {(row[0], row[4]): row for row in rows}

    documents: list[CorpusDocument] = []
    for item in eligible_items:
        row = row_by_identity.get(item.identity)
        if row is None:
            raise CorpusIntegrityError(
                f"database is missing frozen skill {item.repository_full_name}:{item.path}"
            )
        (
            repository_id,
            repository_full_name,
            license_status,
            skill_id,
            path,
            content_sha256,
            name,
            description,
            declared_license,
            compatibility,
            allowed_tools,
            metadata_json,
            body_text,
            safe_snippet,
            validation_status,
            has_scripts,
        ) = row
        _validate_database_row(
            item,
            repository_full_name=repository_full_name,
            content_sha256=content_sha256,
            validation_status=validation_status,
        )
        fields = _build_lexical_fields(
            name=name,
            description=description,
            declared_license=declared_license,
            compatibility=compatibility,
            allowed_tools=allowed_tools,
            metadata_json=metadata_json,
            body_text=body_text,
        )
        documents.append(
            CorpusDocument(
                document_id=f"github:{repository_id}:{path}",
                skill_id=skill_id,
                repository_id=repository_id,
                repository_full_name=repository_full_name,
                path=path,
                name=name,
                safe_snippet=safe_snippet,
                validation_status=validation_status,
                content_sha256=content_sha256,
                fields=fields,
                tokens=tokenize(fields.combined_text),
                license_status=license_status,
                has_scripts=has_scripts,
            )
        )

    documents.sort(
        key=lambda document: (
            document.repository_full_name.casefold(),
            document.path.casefold(),
            document.document_id,
        )
    )
    if len(documents) != len(eligible_items):
        raise CorpusIntegrityError("database and frozen eligible-skill counts do not reconcile")

    return FrozenCorpus(
        snapshot_path=resolved_snapshot_path.as_posix(),
        snapshot_sha256=snapshot_sha256,
        documents=tuple(documents),
    )


def _read_bytes(path: Path, label: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as error:
        raise CorpusIntegrityError(f"{label} could not be read: {path}") from error


def _validate_database_row(
    item: DatasetSnapshotItem,
    *,
    repository_full_name: str,
    content_sha256: str,
    validation_status: ValidationStatus,
) -> None:
    if repository_full_name.casefold() != item.repository_full_name.casefold():
        raise CorpusIntegrityError("stored repository name differs from the frozen snapshot")
    if content_sha256 != item.content_sha256:
        raise StaleCorpusError(
            f"stored content hash differs for {item.repository_full_name}:{item.path}"
        )
    if validation_status is not item.validation_status:
        raise StaleCorpusError(
            f"stored validation status differs for {item.repository_full_name}:{item.path}"
        )


def _build_lexical_fields(
    *,
    name: str,
    description: str,
    declared_license: str | None,
    compatibility: str | None,
    allowed_tools: list[str],
    metadata_json: dict[str, object],
    body_text: str,
) -> LexicalFields:
    headings, body_without_headings = partition_markdown_body(body_text)
    metadata_parts: list[str] = []
    if declared_license:
        metadata_parts.append(declared_license)
    if compatibility:
        metadata_parts.append(compatibility)
    metadata_parts.extend(sorted(allowed_tools, key=str.casefold))
    for key in sorted(metadata_json, key=str.casefold):
        value = metadata_json[key]
        metadata_parts.append(key)
        if isinstance(value, str):
            metadata_parts.append(value)

    return LexicalFields(
        name_text=normalize_lexical_text(name),
        description_text=normalize_lexical_text(description),
        metadata_text=normalize_lexical_text(" ".join(metadata_parts)),
        heading_text=" ".join(headings),
        body_text=body_without_headings,
    )
