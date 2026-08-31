"""Dependency-overridden fixtures for public API contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from skillscope.api.dependencies import (
    SearchCapacity,
    get_api_service,
    get_db_session,
    get_search_capacity,
)
from skillscope.api.main import create_app
from skillscope.api.schemas import (
    BM25ScoreComponents,
    BM25TermContribution,
    DatasetSnapshotReference,
    DenseScoreComponents,
    EvaluationConfiguration,
    EvaluationLatency,
    EvaluationMetrics,
    FeatureCounts,
    HybridScoreComponents,
    LatestEvaluationResponse,
    ReadinessCheck,
    RepositoryDetail,
    RepositorySummary,
    SearchResponse,
    SearchResult,
    SkillDetailResponse,
    StatsResponse,
    StructuralSignalsResponse,
    SupportingFileResponse,
    ToolCount,
    ValidationMessageResponse,
)
from skillscope.api.service import SkillNotFoundError
from skillscope.core.config import Settings
from skillscope.db.enums import (
    LicenseStatus,
    RetrievalMethod,
    SupportingFileType,
    ValidationStatus,
)
from skillscope.parsing.models import ValidationSeverity
from skillscope.retrieval.filters import RetrievalFilters

SKILL_ID = UUID("11111111-1111-4111-8111-111111111111")
SNAPSHOT_SHA = "a" * 64
REPORT_SHA = "b" * 64
GENERATED_AT = datetime(2030, 1, 1, tzinfo=UTC)


class FakeApiService:
    """Deterministic response fixture implementing the route-facing service methods."""

    def __init__(self) -> None:
        self.ready = True
        self.missing_skill = False
        self.last_search: dict[str, object] = {}

    def readiness(self, session: object) -> tuple[bool, dict[str, ReadinessCheck]]:
        del session
        status = "ok" if self.ready else "failed"
        detail = "Dependency is ready." if self.ready else "Dependency is unavailable."
        return self.ready, {
            "database": ReadinessCheck(status=status, detail=detail),
            "retrieval": ReadinessCheck(status=status, detail=detail),
            "model_runtime": ReadinessCheck(status=status, detail=detail),
        }

    def search(
        self,
        session: object,
        *,
        request_id: str,
        query: str,
        mode: RetrievalMethod,
        limit: int,
        filters: RetrievalFilters,
    ) -> SearchResponse:
        del session
        self.last_search = {
            "query": query,
            "mode": mode,
            "limit": limit,
            "filters": filters,
        }
        if mode is RetrievalMethod.BM25:
            score = 8.5
            components = BM25ScoreComponents(
                matched_terms=("spreadsheet",),
                term_contributions=(
                    BM25TermContribution(
                        term="spreadsheet",
                        term_frequency=2,
                        document_frequency=3,
                        inverse_document_frequency=1.25,
                        score=8.5,
                    ),
                ),
            )
        elif mode is RetrievalMethod.DENSE:
            score = 0.91
            components = DenseScoreComponents(
                cosine_similarity=0.91,
                cosine_distance=0.09,
            )
        else:
            score = 0.031
            components = HybridScoreComponents(
                rrf_score=0.031,
                bm25_rank=2,
                dense_rank=1,
                bm25_score=8.5,
                dense_similarity=0.91,
            )
        return SearchResponse(
            request_id=request_id,
            query=query,
            mode=mode,
            limit=limit,
            took_ms=1.25,
            score_semantics="Compare scores only within this response.",
            dataset_snapshot=_snapshot(),
            results=(
                SearchResult(
                    rank=1,
                    skill_id=SKILL_ID,
                    name="xlsx",
                    description="Create and edit spreadsheets.",
                    snippet="Safe display metadata only.",
                    repository=RepositorySummary(
                        full_name="example/skills",
                        url="https://github.com/example/skills",
                        stars=42,
                        license_status=LicenseStatus.PERMISSIVE,
                    ),
                    path="skills/xlsx/SKILL.md",
                    source_url=("https://github.com/example/skills/blob/main/skills/xlsx/SKILL.md"),
                    validation_status=ValidationStatus.VALID,
                    has_scripts=True,
                    score=score,
                    score_components=components,
                ),
            ),
        )

    def skill_detail(
        self,
        session: object,
        *,
        request_id: str,
        skill_id: UUID,
    ) -> SkillDetailResponse:
        del session
        if self.missing_skill or skill_id != SKILL_ID:
            raise SkillNotFoundError(str(skill_id))
        return SkillDetailResponse(
            request_id=request_id,
            skill_id=SKILL_ID,
            name="xlsx",
            description="Create and edit spreadsheets.",
            path="skills/xlsx/SKILL.md",
            source_url="https://github.com/example/skills/blob/main/skills/xlsx/SKILL.md",
            declared_license="MIT",
            compatibility="Python 3.12",
            allowed_tools=("Read",),
            metadata={"category": "documents"},
            validation_status=ValidationStatus.WARNING,
            validation_messages=(
                ValidationMessageResponse(
                    code="root_directory_name_unverified",
                    severity=ValidationSeverity.WARNING,
                    message="Directory identity could not be verified.",
                ),
            ),
            structural_signals=StructuralSignalsResponse(
                has_scripts=True,
                has_references=True,
                has_assets=False,
                script_count=1,
                reference_count=1,
                asset_count=0,
                heading_count=3,
                code_block_count=2,
                external_link_count=1,
                word_count=120,
                byte_count=900,
            ),
            supporting_files=(
                SupportingFileResponse(
                    relative_path="scripts/check.py",
                    file_type=SupportingFileType.SCRIPT,
                    size_bytes=250,
                    extension=".py",
                ),
            ),
            repository=RepositoryDetail(
                full_name="example/skills",
                url="https://github.com/example/skills",
                default_branch="main",
                stars=42,
                forks=4,
                license_status=LicenseStatus.PERMISSIVE,
                license_spdx_id="MIT",
                license_name="MIT License",
            ),
            excerpt="Bounded inert plain text.",
            excerpt_truncated=True,
            first_seen_at=GENERATED_AT,
            last_seen_at=GENERATED_AT,
        )

    def stats(self, session: object, *, request_id: str) -> StatsResponse:
        del session
        return StatsResponse(
            request_id=request_id,
            repository_count=1,
            skill_count=2,
            retrieval_eligible_skill_count=1,
            validation_statuses={
                ValidationStatus.VALID: 1,
                ValidationStatus.WARNING: 0,
                ValidationStatus.INVALID: 1,
            },
            license_statuses={
                LicenseStatus.PERMISSIVE: 1,
                LicenseStatus.RESTRICTIVE: 0,
                LicenseStatus.MISSING: 0,
                LicenseStatus.UNKNOWN: 0,
            },
            features=FeatureCounts(scripts=1, references=1, assets=0),
            common_declared_tools=(ToolCount(tool="read", count=1),),
            latest_ingestion_at=GENERATED_AT,
            dataset_snapshot=_snapshot(),
        )

    def latest_evaluation(self, *, request_id: str) -> LatestEvaluationResponse:
        methods = tuple(
            EvaluationMetrics(
                method=method,
                query_count=8,
                ndcg_at_10=0.8,
                mrr_at_10=0.9,
                recall_at_10=0.85,
                latency=EvaluationLatency(
                    p50_ms=1.0,
                    p95_ms=2.0,
                    sample_count=8,
                ),
            )
            for method in RetrievalMethod
        )
        return LatestEvaluationResponse(
            request_id=request_id,
            generated_at=GENERATED_AT,
            git_commit="c" * 40,
            split="test",
            report_sha256=REPORT_SHA,
            dataset_snapshot=_snapshot(),
            configuration=EvaluationConfiguration(
                model_id="sentence-transformers/all-MiniLM-L6-v2",
                model_revision="d" * 40,
                model_dimension=384,
                exact_dense_search=True,
                rrf_candidate_depth=50,
                rrf_k=60,
                bm25_weight=1.0,
                dense_weight=1.0,
                cutoff=10,
            ),
            methods=(methods[0], methods[1], methods[2]),
        )


class RejectingCapacity(SearchCapacity):
    """Test double that always returns the documented 429 path."""

    def __init__(self) -> None:
        self.released = False

    def acquire(self) -> bool:
        return False

    def release(self) -> None:
        self.released = True


@pytest.fixture
def fake_service() -> FakeApiService:
    return FakeApiService()


@pytest.fixture
def api_client(fake_service: FakeApiService) -> Iterator[TestClient]:
    settings = Settings(
        _env_file=None,
        environment="test",
        frontend_origin="http://frontend.example",
    )
    application = create_app(settings)
    application.dependency_overrides[get_api_service] = lambda: fake_service
    application.dependency_overrides[get_db_session] = lambda: object()
    application.dependency_overrides[get_search_capacity] = lambda: SearchCapacity(1)
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client
    application.dependency_overrides.clear()


def _snapshot() -> DatasetSnapshotReference:
    return DatasetSnapshotReference(
        path="data/manifests/dataset-snapshot.jsonl",
        sha256=SNAPSHOT_SHA,
    )
