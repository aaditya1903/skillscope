"""PostgreSQL-backed integrity tests for the frozen BM25 corpus."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from skillscope.db.enums import (
    IngestionItemStatus,
    LicenseStatus,
    ValidationStatus,
)
from skillscope.db.models import Repository, Skill
from skillscope.ingestion.snapshot import (
    DatasetSnapshot,
    DatasetSnapshotHeader,
    DatasetSnapshotItem,
    write_dataset_snapshot,
)
from skillscope.retrieval.config import BM25BaselineConfig
from skillscope.retrieval.corpus import StaleCorpusError, load_frozen_corpus

pytestmark = pytest.mark.integration


def _skill(repository: Repository, name: str, status: ValidationStatus) -> Skill:
    digit = {"alpha": "1", "beta": "2", "gamma": "3"}[name]
    return Skill(
        repository=repository,
        path=f"skills/{name}/SKILL.md",
        html_url=f"https://github.com/example/catalogue/blob/main/skills/{name}/SKILL.md",
        raw_url=None,
        git_blob_sha=digit * 40,
        content_sha256=digit * 64,
        name=name,
        description=f"{name.title()} database automation skill.",
        declared_license="MIT",
        compatibility="Python 3.12",
        allowed_tools=["uv", "pytest"],
        metadata_json={"category": "testing"},
        extension_fields_json={},
        body_text=f"# {name.title()} usage\nRun the {name} workflow with CI/CD.\n",
        search_text=f"{name} database automation",
        safe_snippet=f"{name.title()} database automation skill.",
        embedding=None,
        validation_status=status,
        validation_messages_json=[],
        indexed_at=None,
    )


def _prepare_corpus(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[BM25BaselineConfig, Skill]:
    monkeypatch.chdir(tmp_path)
    candidate_bytes = b'{"record_type":"synthetic-candidate-evidence"}\n'
    candidate_path = Path("candidates.jsonl")
    candidate_path.write_bytes(candidate_bytes)

    repository = Repository(
        github_repository_id=7_777,
        owner="example",
        name="catalogue",
        full_name="example/catalogue",
        html_url="https://github.com/example/catalogue",
        default_branch="main",
        description="Synthetic retrieval fixture.",
        license_spdx_id="MIT",
        license_name="MIT License",
        license_status=LicenseStatus.PERMISSIVE,
        pushed_at=None,
        etag='"retrieval"',
    )
    valid = _skill(repository, "alpha", ValidationStatus.VALID)
    warning = _skill(repository, "beta", ValidationStatus.WARNING)
    invalid = _skill(repository, "gamma", ValidationStatus.INVALID)
    db_session.add_all([repository, valid, warning, invalid])
    db_session.flush()

    items = (
        DatasetSnapshotItem(
            repository_id=repository.github_repository_id,
            repository_full_name=repository.full_name,
            path=valid.path,
            git_blob_sha=valid.git_blob_sha,
            status=IngestionItemStatus.INGESTED,
            content_sha256=valid.content_sha256,
            stored=True,
            validation_status=ValidationStatus.VALID,
        ),
        DatasetSnapshotItem(
            repository_id=repository.github_repository_id,
            repository_full_name=repository.full_name,
            path=warning.path,
            git_blob_sha=warning.git_blob_sha,
            status=IngestionItemStatus.INGESTED,
            content_sha256=warning.content_sha256,
            stored=True,
            validation_status=ValidationStatus.WARNING,
        ),
        DatasetSnapshotItem(
            repository_id=repository.github_repository_id,
            repository_full_name=repository.full_name,
            path=invalid.path,
            git_blob_sha=invalid.git_blob_sha,
            status=IngestionItemStatus.INVALID,
            content_sha256=invalid.content_sha256,
            stored=True,
            validation_status=ValidationStatus.INVALID,
            failure={
                "category": "validation",
                "codes": ["field_invalid"],
                "message": "Parser reported invalid skill content.",
            },
        ),
    )
    snapshot = DatasetSnapshot(
        header=DatasetSnapshotHeader(
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="a" * 40,
            ingestion_run_id=uuid4(),
            candidate_manifest_path=candidate_path.as_posix(),
            candidate_manifest_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            candidate_count=3,
            item_count=3,
            repository_count=1,
            stored_skill_count=3,
            ingested_count=2,
            unchanged_count=0,
            invalid_count=1,
            skipped_count=0,
            error_count=0,
            valid_skill_count=1,
            warning_skill_count=1,
            invalid_skill_count=1,
        ),
        items=items,
    )
    snapshot_path = Path("snapshot.jsonl")
    write_dataset_snapshot(snapshot_path, snapshot)
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    config = BM25BaselineConfig(
        k1=1.5,
        b=0.75,
        default_top_k=10,
        corpus_snapshot_path=snapshot_path.as_posix(),
        corpus_snapshot_sha256=snapshot_sha256,
        eligible_validation_statuses=("valid", "warning"),
    )
    return config, valid


def test_loader_selects_valid_and_warning_skills_and_builds_separate_fields(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = _prepare_corpus(db_session, tmp_path, monkeypatch)

    corpus = load_frozen_corpus(db_session, config)

    assert len(corpus.documents) == 2
    assert [document.validation_status for document in corpus.documents] == [
        ValidationStatus.VALID,
        ValidationStatus.WARNING,
    ]
    first = corpus.documents[0]
    assert first.fields.name_text == "alpha"
    assert first.fields.heading_text == "alpha usage"
    assert "alpha usage" not in first.fields.body_text
    assert "python 3.12" in first.fields.metadata_text
    assert "ci/cd" in first.tokens


def test_loader_rejects_changed_snapshot_bytes(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = _prepare_corpus(db_session, tmp_path, monkeypatch)
    changed = config.model_copy(update={"corpus_snapshot_sha256": "f" * 64})

    with pytest.raises(StaleCorpusError, match="baseline configuration"):
        load_frozen_corpus(db_session, changed)


def test_loader_rejects_database_content_drift(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, valid = _prepare_corpus(db_session, tmp_path, monkeypatch)
    valid.content_sha256 = "f" * 64
    db_session.flush()

    with pytest.raises(StaleCorpusError, match="stored content hash differs"):
        load_frozen_corpus(db_session, config)


def test_loader_rejects_candidate_manifest_drift(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, _ = _prepare_corpus(db_session, tmp_path, monkeypatch)
    Path("candidates.jsonl").write_bytes(b"changed\n")

    with pytest.raises(StaleCorpusError, match="candidate manifest"):
        load_frozen_corpus(db_session, config)
