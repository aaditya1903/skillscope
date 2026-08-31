"""PostgreSQL-backed API retrieval, readiness, stats, and detail coverage."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session

from skillscope.api.dependencies import get_api_service, get_db_session
from skillscope.api.main import create_app
from skillscope.api.service import SkillScopeApiService
from skillscope.core.config import Settings
from skillscope.db.enums import (
    IngestionItemStatus,
    LicenseStatus,
    SupportingFileType,
    ValidationStatus,
)
from skillscope.db.models import Repository, Skill, SkillFile
from skillscope.ingestion.snapshot import (
    DatasetSnapshot,
    DatasetSnapshotHeader,
    DatasetSnapshotItem,
    write_dataset_snapshot,
)
from skillscope.retrieval.config import BM25BaselineConfig, DenseHybridConfig
from skillscope.retrieval.corpus import StaleCorpusError, load_frozen_corpus
from skillscope.retrieval.embeddings import index_frozen_corpus_embeddings

pytestmark = pytest.mark.integration
MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
MODEL_REVISION = "1" * 40
BODY_SENTINEL = "RAW_BODY_SENTINEL_MUST_NOT_LEAK"


class DeterministicApiEncoder:
    """Map alpha and beta test text onto exact orthogonal unit vectors."""

    model_id = MODEL_ID
    model_revision = MODEL_REVISION
    dimension = 384

    def encode(self, texts: tuple[str, ...], *, batch_size: int) -> np.ndarray:
        del batch_size
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for index, text in enumerate(texts):
            matrix[index, 0 if "alpha" in text.casefold() else 1] = 1.0
        return matrix


def test_real_api_executes_all_modes_and_returns_safe_database_evidence(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, alpha_id = _prepare_api_service(db_session, tmp_path, monkeypatch)
    application = create_app(
        Settings(
            _env_file=None,
            environment="test",
            frontend_origin="http://frontend.example",
        )
    )
    application.dependency_overrides[get_db_session] = lambda: db_session
    application.dependency_overrides[get_api_service] = lambda: service

    with TestClient(application, raise_server_exceptions=False) as client:
        readiness = client.get("/readyz")
        assert readiness.status_code == 200
        assert readiness.json()["status"] == "ready"

        for mode in ("bm25", "dense", "hybrid"):
            response = client.get(
                "/api/v1/search",
                params={
                    "q": "alpha workflow",
                    "mode": mode,
                    "limit": 2,
                    "license_status": "permissive",
                },
            )
            assert response.status_code == 200, response.text
            payload = response.json()
            assert payload["mode"] == mode
            assert payload["results"][0]["skill_id"] == str(alpha_id)
            assert payload["results"][0]["score_components"]["method"] == mode
            assert BODY_SENTINEL not in response.text

        filtered = client.get(
            "/api/v1/search",
            params={
                "q": "beta workflow",
                "mode": "dense",
                "has_scripts": "true",
            },
        )
        assert filtered.status_code == 200
        assert [item["skill_id"] for item in filtered.json()["results"]] == [str(alpha_id)]

        detail = client.get(f"/api/v1/skills/{alpha_id}")
        assert detail.status_code == 200
        assert detail.json()["excerpt_truncated"] is True
        assert detail.json()["supporting_files"][0]["relative_path"] == "scripts/alpha.py"
        assert BODY_SENTINEL not in detail.text

        stats = client.get("/api/v1/stats")
        assert stats.status_code == 200
        assert stats.json()["repository_count"] == 1
        assert stats.json()["skill_count"] == 2
        assert stats.json()["retrieval_eligible_skill_count"] == 2
        assert stats.json()["features"]["scripts"] == 1

    application.dependency_overrides.clear()


def _prepare_api_service(
    session: Session,
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[SkillScopeApiService, object]:
    monkeypatch.chdir(root)
    data_directory = root / "data"
    config_directory = root / "config"
    report_directory = root / "reports"
    data_directory.mkdir()
    config_directory.mkdir()
    report_directory.mkdir()

    candidate_path = data_directory / "candidates.jsonl"
    candidate_bytes = b'{"record_type":"synthetic-api-candidates"}\n'
    candidate_path.write_bytes(candidate_bytes)

    repository = Repository(
        github_repository_id=444_444,
        owner="example",
        name="skills",
        full_name="example/skills",
        html_url="https://github.com/example/skills",
        default_branch="main",
        description="Synthetic API integration repository.",
        stars_count=42,
        forks_count=4,
        open_issues_count=0,
        is_fork=False,
        is_archived=False,
        license_spdx_id="MIT",
        license_name="MIT License",
        license_status=LicenseStatus.PERMISSIVE,
        pushed_at=None,
        etag='"api-integration"',
    )
    alpha = _skill(repository, name="alpha", digit="1", has_scripts=True)
    beta = _skill(repository, name="beta", digit="2", has_scripts=False)
    session.add_all([repository, alpha, beta])
    session.flush()
    session.add(
        SkillFile(
            skill_id=alpha.id,
            relative_path="scripts/alpha.py",
            file_type=SupportingFileType.SCRIPT,
            size_bytes=120,
            git_blob_sha="3" * 40,
            extension=".py",
        )
    )
    session.flush()

    snapshot = DatasetSnapshot(
        header=DatasetSnapshotHeader(
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="4" * 40,
            ingestion_run_id=uuid4(),
            candidate_manifest_path="data/candidates.jsonl",
            candidate_manifest_sha256=hashlib.sha256(candidate_bytes).hexdigest(),
            candidate_count=2,
            item_count=2,
            repository_count=1,
            stored_skill_count=2,
            ingested_count=2,
            unchanged_count=0,
            invalid_count=0,
            skipped_count=0,
            error_count=0,
            valid_skill_count=2,
            warning_skill_count=0,
            invalid_skill_count=0,
        ),
        items=(
            _snapshot_item(repository, alpha),
            _snapshot_item(repository, beta),
        ),
    )
    snapshot_path = Path("data/snapshot.jsonl")
    write_dataset_snapshot(snapshot_path, snapshot)
    snapshot_sha256 = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()

    bm25_config = BM25BaselineConfig(
        k1=1.5,
        b=0.75,
        default_top_k=10,
        corpus_snapshot_path="data/snapshot.jsonl",
        corpus_snapshot_sha256=snapshot_sha256,
        eligible_validation_statuses=("valid", "warning"),
    )
    bm25_bytes = _canonical_json(bm25_config.model_dump(mode="json"))
    bm25_path = config_directory / "bm25.json"
    bm25_path.write_bytes(bm25_bytes)

    dense_config = DenseHybridConfig(
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        sentence_transformers_version="6.0.0",
        batch_size=2,
        default_top_k=10,
        bm25_weight=1.0,
        dense_weight=1.0,
        corpus_snapshot_path="data/snapshot.jsonl",
        corpus_snapshot_sha256=snapshot_sha256,
        bm25_config_path="config/bm25.json",
        bm25_config_sha256=hashlib.sha256(bm25_bytes).hexdigest(),
        eligible_validation_statuses=("valid", "warning"),
    )
    dense_path = config_directory / "dense.json"
    dense_bytes = _canonical_json(dense_config.model_dump(mode="json"))
    dense_path.write_bytes(dense_bytes)

    corpus = load_frozen_corpus(session, bm25_config, snapshot_path=snapshot_path)
    encoder = DeterministicApiEncoder()
    index_frozen_corpus_embeddings(
        session,
        corpus,
        dense_config,
        encoder,
        embedding_config_sha256=hashlib.sha256(dense_bytes).hexdigest(),
        indexed_at=datetime(2030, 1, 2, tzinfo=UTC),
    )
    session.flush()

    service = SkillScopeApiService(
        project_root=root,
        bm25_config_path="config/bm25.json",
        dense_config_path="config/dense.json",
        evaluation_report_path="reports/evaluation.json",
        encoder_factory=lambda config: encoder,
        version_reader=lambda package: "6.0.0",
    )
    return service, alpha.id


def _skill(
    repository: Repository,
    *,
    name: str,
    digit: str,
    has_scripts: bool,
) -> Skill:
    body = f"# {name.title()}\n\n{name} workflow.\n" + ("z" * 2_100) + BODY_SENTINEL
    return Skill(
        repository=repository,
        path=f"skills/{name}/SKILL.md",
        html_url=f"https://github.com/example/skills/blob/main/skills/{name}/SKILL.md",
        raw_url=None,
        git_blob_sha=digit * 40,
        content_sha256=digit * 64,
        name=name,
        description=f"Synthetic {name} workflow skill.",
        declared_license="MIT",
        compatibility="Python 3.12",
        allowed_tools=["Read"],
        metadata_json={"category": "testing"},
        extension_fields_json={"untrusted": "not returned"},
        body_text=body,
        search_text=f"{name} workflow",
        safe_snippet=f"Synthetic {name} workflow skill.",
        embedding=None,
        validation_status=ValidationStatus.VALID,
        validation_messages_json=[],
        has_scripts=has_scripts,
        has_references=False,
        has_assets=False,
        script_count=1 if has_scripts else 0,
        heading_count=1,
        word_count=4,
        byte_count=len(body.encode()),
        indexed_at=None,
    )


def _snapshot_item(
    repository: Repository,
    skill: Skill,
) -> DatasetSnapshotItem:
    return DatasetSnapshotItem(
        repository_id=repository.github_repository_id,
        repository_full_name=repository.full_name,
        path=skill.path,
        git_blob_sha=skill.git_blob_sha,
        status=IngestionItemStatus.INGESTED,
        content_sha256=skill.content_sha256,
        stored=True,
        validation_status=skill.validation_status,
    )


def _canonical_json(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def test_retrieval_assets_are_reused_until_stored_evidence_changes(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _ = _prepare_api_service(db_session, tmp_path, monkeypatch)

    first = service._load_assets(db_session)
    second = service._load_assets(db_session)

    assert second is first

    db_session.execute(update(Skill).values(content_sha256="9" * 64))
    db_session.flush()

    # A cached corpus must never mask drift the full rebuild would have rejected.
    with pytest.raises(StaleCorpusError):
        service._load_assets(db_session)


def test_stats_folds_separator_suffixed_declared_tools_together(
    db_session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, alpha_id = _prepare_api_service(db_session, tmp_path, monkeypatch)
    db_session.execute(
        update(Skill).where(Skill.id == alpha_id).values(allowed_tools=["Read,", "Grep;", " "])
    )
    db_session.flush()

    response = service.stats(db_session, request_id="c" * 32)

    assert [(item.tool, item.count) for item in response.common_declared_tools] == [
        ("read", 2),
        ("grep", 1),
    ]
