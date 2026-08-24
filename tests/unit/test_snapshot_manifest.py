"""Unit coverage for canonical body-free dataset snapshots."""

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from skillscope.db.enums import IngestionItemStatus, ValidationStatus
from skillscope.ingestion.snapshot import (
    DatasetSnapshot,
    DatasetSnapshotHeader,
    DatasetSnapshotItem,
    SnapshotValidationError,
    read_dataset_snapshot,
    serialize_dataset_snapshot,
    write_dataset_snapshot,
)


def _item(
    name: str,
    *,
    repository_id: int,
    status: IngestionItemStatus = IngestionItemStatus.INGESTED,
) -> DatasetSnapshotItem:
    stored = status in {IngestionItemStatus.INGESTED, IngestionItemStatus.UNCHANGED}
    failure = None if stored else {"category": "validation", "message": "Safe failure."}
    return DatasetSnapshotItem(
        repository_id=repository_id,
        repository_full_name="skillscope-tests/catalogue",
        path=f"skills/{name}/SKILL.md",
        git_blob_sha=f"{repository_id % 10}" * 40,
        status=status,
        content_sha256=f"{repository_id % 10}" * 64,
        stored=stored,
        validation_status=ValidationStatus.VALID if stored else None,
        failure=failure,
    )


def _snapshot() -> DatasetSnapshot:
    items = (
        _item("alpha", repository_id=1),
        _item("beta", repository_id=2, status=IngestionItemStatus.INVALID),
    )
    return DatasetSnapshot(
        header=DatasetSnapshotHeader(
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="a" * 40,
            ingestion_run_id=uuid4(),
            candidate_manifest_path="data/manifests/candidates.jsonl",
            candidate_manifest_sha256="b" * 64,
            candidate_count=2,
            item_count=2,
            repository_count=1,
            stored_skill_count=1,
            ingested_count=1,
            unchanged_count=0,
            invalid_count=1,
            skipped_count=0,
            error_count=0,
            valid_skill_count=1,
            warning_skill_count=0,
            invalid_skill_count=0,
        ),
        items=items,
    )


def test_serialization_is_canonical_body_free_jsonl() -> None:
    serialized = serialize_dataset_snapshot(_snapshot())

    assert serialized.endswith(b"\n")
    assert len(serialized.splitlines()) == 3
    assert b"body_text" not in serialized
    assert b"github_pat_" not in serialized
    assert serialize_dataset_snapshot(_snapshot()).splitlines()[1:] == serialized.splitlines()[1:]


def test_write_and_read_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = _snapshot()
    monkeypatch.chdir(tmp_path)
    output = Path("snapshot.jsonl")

    write_dataset_snapshot(output, snapshot)

    assert read_dataset_snapshot(output) == snapshot


def test_reader_rejects_noncanonical_json(tmp_path: Path) -> None:
    output = tmp_path / "snapshot.jsonl"
    canonical = serialize_dataset_snapshot(_snapshot())
    records = [json.loads(line) for line in canonical.splitlines()]
    output.write_text("\n".join(json.dumps(record) for record in records) + "\n")

    with pytest.raises(SnapshotValidationError, match="canonically"):
        read_dataset_snapshot(output)


def test_reader_rejects_missing_final_newline(tmp_path: Path) -> None:
    output = tmp_path / "snapshot.jsonl"
    output.write_bytes(serialize_dataset_snapshot(_snapshot()).rstrip(b"\n"))

    with pytest.raises(SnapshotValidationError, match="newline"):
        read_dataset_snapshot(output)


def test_document_rejects_duplicate_or_unsorted_items() -> None:
    first = _item("alpha", repository_id=1)
    second = _item("beta", repository_id=2)
    snapshot = _snapshot()

    with pytest.raises(SnapshotValidationError, match="duplicate"):
        serialize_dataset_snapshot(DatasetSnapshot(header=snapshot.header, items=(first, first)))
    with pytest.raises(SnapshotValidationError, match="sorted"):
        serialize_dataset_snapshot(DatasetSnapshot(header=snapshot.header, items=(second, first)))


def test_header_rejects_unreconciled_counts() -> None:
    values = _snapshot().header.model_dump()
    values["error_count"] = 1

    with pytest.raises(ValidationError, match="statuses"):
        DatasetSnapshotHeader.model_validate(values)


def test_header_requires_timezone_and_safe_manifest_path() -> None:
    values = _snapshot().header.model_dump()
    values["generated_at"] = datetime(2030, 1, 1)
    with pytest.raises(ValidationError, match="timezone"):
        DatasetSnapshotHeader.model_validate(values)

    values = _snapshot().header.model_dump()
    values["candidate_manifest_path"] = "../candidates.jsonl"
    with pytest.raises(ValidationError, match="safe relative"):
        DatasetSnapshotHeader.model_validate(values)


def test_item_requires_storage_and_failure_evidence_consistent_with_status() -> None:
    values = _item("alpha", repository_id=1).model_dump()
    values["stored"] = False
    values["validation_status"] = None
    with pytest.raises(ValidationError, match="must be stored"):
        DatasetSnapshotItem.model_validate(values)

    values = _item("beta", repository_id=2, status=IngestionItemStatus.INVALID).model_dump()
    values["failure"] = None
    with pytest.raises(ValidationError, match="failure evidence"):
        DatasetSnapshotItem.model_validate(values)
