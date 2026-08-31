"""Strict response models for the public SkillScope HTTP API."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from skillscope.db.enums import (
    LicenseStatus,
    RetrievalMethod,
    SupportingFileType,
    ValidationStatus,
)
from skillscope.parsing.models import ValidationSeverity


class ApiModel(BaseModel):
    """Forbid accidental response-field drift across the public API."""

    model_config = ConfigDict(extra="forbid")


class HealthResponse(ApiModel):
    """Response returned by the process-liveness endpoint."""

    status: Literal["ok"] = "ok"
    service: str
    version: str


class ReadinessCheck(ApiModel):
    """One safe dependency check reported by the readiness endpoint."""

    status: Literal["ok", "failed"]
    detail: str


class ReadinessResponse(ApiModel):
    """Readiness of the database and frozen retrieval evidence."""

    status: Literal["ready", "not_ready"]
    service: str
    version: str
    checks: dict[str, ReadinessCheck]


class ErrorField(ApiModel):
    """One safe, input-free request-validation issue."""

    field: str
    code: str
    message: str


class ErrorDetail(ApiModel):
    """Stable machine-readable error information."""

    code: str
    message: str
    fields: tuple[ErrorField, ...] = ()


class ErrorResponse(ApiModel):
    """Common error envelope returned by every API route."""

    request_id: str
    error: ErrorDetail


class DatasetSnapshotReference(ApiModel):
    """Identity of the frozen retrieval corpus used by a response."""

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RepositorySummary(ApiModel):
    """Safe repository metadata attached to a search result."""

    full_name: str
    url: str
    stars: int = Field(ge=0)
    license_status: LicenseStatus


class BM25TermContribution(ApiModel):
    """Transparent contribution of one normalized query term."""

    term: str
    term_frequency: int = Field(ge=1)
    document_frequency: int = Field(ge=1)
    inverse_document_frequency: float = Field(ge=0.0)
    score: float = Field(ge=0.0)


class BM25ScoreComponents(ApiModel):
    """Components of a BM25 score; not comparable to other methods."""

    method: Literal[RetrievalMethod.BM25] = RetrievalMethod.BM25
    matched_terms: tuple[str, ...]
    term_contributions: tuple[BM25TermContribution, ...]


class DenseScoreComponents(ApiModel):
    """Components of an exact cosine-similarity score."""

    method: Literal[RetrievalMethod.DENSE] = RetrievalMethod.DENSE
    cosine_similarity: float = Field(ge=-1.0, le=1.0)
    cosine_distance: float = Field(ge=0.0)


class HybridScoreComponents(ApiModel):
    """Rank and source evidence for one reciprocal-rank-fusion score."""

    method: Literal[RetrievalMethod.HYBRID] = RetrievalMethod.HYBRID
    rrf_score: float = Field(gt=0.0)
    bm25_rank: int | None = Field(default=None, ge=1)
    dense_rank: int | None = Field(default=None, ge=1)
    bm25_score: float | None = Field(default=None, ge=0.0)
    dense_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)


ScoreComponents = Annotated[
    BM25ScoreComponents | DenseScoreComponents | HybridScoreComponents,
    Field(discriminator="method"),
]


class SearchResult(ApiModel):
    """One ranked skill with safe display metadata and score evidence."""

    rank: int = Field(ge=1, le=50)
    skill_id: UUID
    name: str
    description: str
    snippet: str
    repository: RepositorySummary
    path: str
    source_url: str
    validation_status: ValidationStatus
    has_scripts: bool
    score: float
    score_components: ScoreComponents


class SearchResponse(ApiModel):
    """Bounded results from one frozen-corpus retrieval method."""

    request_id: str
    query: str
    mode: RetrievalMethod
    limit: int = Field(ge=1, le=50)
    took_ms: float = Field(ge=0.0)
    score_semantics: str
    dataset_snapshot: DatasetSnapshotReference
    results: tuple[SearchResult, ...]


class ValidationMessageResponse(ApiModel):
    """One stable parser finding stored for a skill."""

    code: str
    severity: ValidationSeverity
    message: str
    field: str | None = None


class StructuralSignalsResponse(ApiModel):
    """Safe counts derived from inert parsing of a skill directory."""

    has_scripts: bool
    has_references: bool
    has_assets: bool
    script_count: int = Field(ge=0)
    reference_count: int = Field(ge=0)
    asset_count: int = Field(ge=0)
    heading_count: int = Field(ge=0)
    code_block_count: int = Field(ge=0)
    external_link_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    byte_count: int = Field(ge=0)


class SupportingFileResponse(ApiModel):
    """Metadata for a supporting file, never its contents."""

    relative_path: str
    file_type: SupportingFileType
    size_bytes: int = Field(ge=0)
    extension: str | None


class RepositoryDetail(ApiModel):
    """Repository provenance and upstream licence evidence."""

    full_name: str
    url: str
    default_branch: str
    stars: int = Field(ge=0)
    forks: int = Field(ge=0)
    license_status: LicenseStatus
    license_spdx_id: str | None
    license_name: str | None


class SkillDetailResponse(ApiModel):
    """Safe, bounded detail for one stored Agent Skill."""

    request_id: str
    skill_id: UUID
    name: str
    description: str
    path: str
    source_url: str
    declared_license: str | None
    compatibility: str | None
    allowed_tools: tuple[str, ...]
    metadata: dict[str, str]
    validation_status: ValidationStatus
    validation_messages: tuple[ValidationMessageResponse, ...]
    structural_signals: StructuralSignalsResponse
    supporting_files: tuple[SupportingFileResponse, ...]
    repository: RepositoryDetail
    excerpt: str
    excerpt_truncated: bool
    first_seen_at: datetime
    last_seen_at: datetime


class FeatureCounts(ApiModel):
    """Counts of skills declaring each supported directory feature."""

    scripts: int = Field(ge=0)
    references: int = Field(ge=0)
    assets: int = Field(ge=0)


class ToolCount(ApiModel):
    """Frequency of one declared tool in stored skill metadata."""

    tool: str
    count: int = Field(ge=1)


class StatsResponse(ApiModel):
    """Aggregate observatory statistics tied to one frozen snapshot."""

    request_id: str
    repository_count: int = Field(ge=0)
    skill_count: int = Field(ge=0)
    retrieval_eligible_skill_count: int = Field(ge=0)
    validation_statuses: dict[ValidationStatus, int]
    license_statuses: dict[LicenseStatus, int]
    features: FeatureCounts
    common_declared_tools: tuple[ToolCount, ...]
    latest_ingestion_at: datetime | None
    dataset_snapshot: DatasetSnapshotReference


class EvaluationLatency(ApiModel):
    """Measured latency summary from the frozen evaluation report."""

    p50_ms: float = Field(ge=0.0)
    p95_ms: float = Field(ge=0.0)
    sample_count: int = Field(ge=1)


class EvaluationMetrics(ApiModel):
    """Held-out effectiveness and latency for one retrieval method."""

    method: RetrievalMethod
    query_count: int = Field(ge=1)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    mrr_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    latency: EvaluationLatency


class EvaluationConfiguration(ApiModel):
    """Pinned configuration reported with the latest evaluation."""

    model_id: str
    model_revision: str
    model_dimension: int
    exact_dense_search: bool
    rrf_candidate_depth: int
    rrf_k: int
    bm25_weight: float
    dense_weight: float
    cutoff: int


class LatestEvaluationResponse(ApiModel):
    """Published summary of the canonical completed test comparison."""

    request_id: str
    generated_at: datetime
    git_commit: str
    split: Literal["test"]
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_snapshot: DatasetSnapshotReference
    configuration: EvaluationConfiguration
    methods: tuple[EvaluationMetrics, EvaluationMetrics, EvaluationMetrics]
