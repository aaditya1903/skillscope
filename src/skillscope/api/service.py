"""Application service exposing frozen retrieval evidence without raw bodies."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from time import perf_counter
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

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
from skillscope.db.enums import (
    IngestionRunStatus,
    LicenseStatus,
    RetrievalMethod,
    ValidationStatus,
)
from skillscope.db.models import IngestionRun, Repository, Skill, SkillFile
from skillscope.evaluation.comparison import RetrievalComparisonReport
from skillscope.parsing.models import ValidationMessage
from skillscope.retrieval.bm25 import BM25Index, BM25Result
from skillscope.retrieval.config import (
    BM25BaselineConfig,
    DenseHybridConfig,
    load_bm25_config,
    load_dense_hybrid_config,
)
from skillscope.retrieval.corpus import (
    FrozenCorpus,
    load_frozen_corpus,
    stored_skill_fingerprint,
)
from skillscope.retrieval.dense import DenseResult, DenseRetriever
from skillscope.retrieval.embeddings import (
    EmbeddingEncoder,
    get_sentence_transformer_encoder,
)
from skillscope.retrieval.filters import RetrievalFilters
from skillscope.retrieval.hybrid import HybridResult, HybridRetriever

MAX_EVALUATION_REPORT_BYTES = 8 * 1024 * 1024
MAX_EXCERPT_CHARACTERS = 2_000
MAX_SAFE_SNIPPET_CHARACTERS = 500
MAX_COMMON_TOOLS = 20


class ApiServiceUnavailableError(RuntimeError):
    """A required database, model, or frozen-evidence dependency is unavailable."""


class SkillNotFoundError(LookupError):
    """The requested stored skill does not exist."""


@dataclass(frozen=True, slots=True)
class RetrievalAssets:
    """Validated configuration and corpus loaded for one request."""

    bm25_config: BM25BaselineConfig
    dense_config: DenseHybridConfig
    dense_config_sha256: str
    corpus: FrozenCorpus
    bm25: BM25Index


@dataclass(frozen=True, slots=True)
class AssetsFingerprint:
    """The evidence a cached corpus is only valid for."""

    bm25_config_sha256: str
    dense_config_sha256: str
    snapshot_sha256: str
    stored_skills: str


EncoderFactory = Callable[[DenseHybridConfig], EmbeddingEncoder]
VersionReader = Callable[[str], str]
ApiScoreComponents = BM25ScoreComponents | DenseScoreComponents | HybridScoreComponents
RankedApiResult = tuple[UUID, float, ApiScoreComponents]


class SkillScopeApiService:
    """Read-only service boundary used by FastAPI routes and deterministic tests."""

    def __init__(
        self,
        *,
        project_root: Path | None = None,
        bm25_config_path: str = "config/retrieval/bm25-v1.json",
        dense_config_path: str = "config/retrieval/dense-hybrid-v1.json",
        evaluation_report_path: str = "reports/evaluation/method-comparison-test-v1.json",
        encoder_factory: EncoderFactory = get_sentence_transformer_encoder,
        version_reader: VersionReader = importlib.metadata.version,
    ) -> None:
        self.project_root = (project_root or Path.cwd()).resolve()
        self.bm25_config_path = self._project_path(bm25_config_path, suffix=".json")
        self.dense_config_path = self._project_path(dense_config_path, suffix=".json")
        self.evaluation_report_path = self._project_path(
            evaluation_report_path,
            suffix=".json",
        )
        self.encoder_factory = encoder_factory
        self.version_reader = version_reader
        self._assets_lock = Lock()
        self._cached_assets: tuple[AssetsFingerprint, RetrievalAssets] | None = None

    def readiness(self, session: Session) -> tuple[bool, dict[str, ReadinessCheck]]:
        """Verify connectivity, frozen-corpus integrity, embeddings, and model runtime."""

        checks: dict[str, ReadinessCheck] = {}
        try:
            database_probe = session.scalar(select(1))
            if database_probe != 1:
                raise ApiServiceUnavailableError("database probe returned an invalid value")
            checks["database"] = ReadinessCheck(status="ok", detail="PostgreSQL is reachable.")
        except (SQLAlchemyError, ApiServiceUnavailableError):
            checks["database"] = ReadinessCheck(
                status="failed",
                detail="PostgreSQL is unavailable.",
            )
            checks["retrieval"] = ReadinessCheck(
                status="failed",
                detail="Retrieval evidence could not be verified.",
            )
            return False, checks

        try:
            assets = self._load_assets(session)
            encoder = self.encoder_factory(assets.dense_config)
            DenseRetriever(
                session,
                assets.corpus,
                assets.dense_config,
                encoder,
                embedding_config_sha256=assets.dense_config_sha256,
            )
            checks["retrieval"] = ReadinessCheck(
                status="ok",
                detail=(
                    f"{len(assets.corpus.documents)} frozen documents and their "
                    "embeddings are current."
                ),
            )
        except (OSError, ValueError, SQLAlchemyError):
            checks["retrieval"] = ReadinessCheck(
                status="failed",
                detail="Frozen retrieval evidence is unavailable or stale.",
            )

        try:
            dense_config = load_dense_hybrid_config(self.dense_config_path)
            runtime_version = self.version_reader("sentence-transformers")
            if runtime_version != dense_config.sentence_transformers_version:
                raise ApiServiceUnavailableError("model runtime version is stale")
            checks["model_runtime"] = ReadinessCheck(
                status="ok",
                detail="The pinned local embedding runtime is installed.",
            )
        except (
            importlib.metadata.PackageNotFoundError,
            OSError,
            ValueError,
            ApiServiceUnavailableError,
        ):
            checks["model_runtime"] = ReadinessCheck(
                status="failed",
                detail="The pinned local embedding runtime is unavailable.",
            )

        ready = all(check.status == "ok" for check in checks.values())
        return ready, checks

    def search(
        self,
        session: Session,
        *,
        request_id: str,
        query: str,
        mode: RetrievalMethod,
        limit: int,
        filters: RetrievalFilters,
    ) -> SearchResponse:
        """Search one frozen corpus and attach safe display metadata."""

        started_at = perf_counter()
        try:
            assets = self._load_assets(session)
            bm25 = assets.bm25
            ranked: tuple[RankedApiResult, ...]
            if mode is RetrievalMethod.BM25:
                ranked = self._bm25_results(bm25.search(query, top_k=limit, filters=filters))
            else:
                encoder = self.encoder_factory(assets.dense_config)
                dense = DenseRetriever(
                    session,
                    assets.corpus,
                    assets.dense_config,
                    encoder,
                    embedding_config_sha256=assets.dense_config_sha256,
                )
                if mode is RetrievalMethod.DENSE:
                    ranked = self._dense_results(dense.search(query, top_k=limit, filters=filters))
                else:
                    hybrid = HybridRetriever(bm25, dense, assets.dense_config)
                    ranked = self._hybrid_results(
                        hybrid.search(query, top_k=limit, filters=filters)
                    )
            results = self._attach_search_metadata(session, ranked)
        except (OSError, ValueError, SQLAlchemyError) as error:
            raise ApiServiceUnavailableError(
                "The frozen retrieval service is unavailable."
            ) from error

        return SearchResponse(
            request_id=request_id,
            query=query,
            mode=mode,
            limit=limit,
            took_ms=round((perf_counter() - started_at) * 1_000.0, 3),
            score_semantics=_score_semantics(mode),
            dataset_snapshot=_snapshot_reference(
                assets.corpus,
                path=assets.bm25_config.corpus_snapshot_path,
            ),
            results=results,
        )

    def skill_detail(
        self,
        session: Session,
        *,
        request_id: str,
        skill_id: UUID,
    ) -> SkillDetailResponse:
        """Return bounded skill detail without loading a full body or any file content."""

        try:
            row = session.execute(
                select(Skill, Repository)
                .join(Repository, Skill.repository_id == Repository.id)
                .where(Skill.id == skill_id)
            ).one_or_none()
            if row is None:
                raise SkillNotFoundError(str(skill_id))
            skill, repository = row
            raw_excerpt = session.scalar(
                select(func.left(Skill.body_text, MAX_EXCERPT_CHARACTERS + 1)).where(
                    Skill.id == skill_id
                )
            )
            excerpt_source = raw_excerpt if isinstance(raw_excerpt, str) else ""
            excerpt = _plain_text(excerpt_source[:MAX_EXCERPT_CHARACTERS])
            messages = tuple(
                ValidationMessage.model_validate(item) for item in skill.validation_messages_json
            )
            files = session.scalars(
                select(SkillFile)
                .where(SkillFile.skill_id == skill_id)
                .order_by(
                    func.lower(SkillFile.relative_path),
                    SkillFile.id,
                )
            ).all()
            metadata = {
                key: value
                for key, value in skill.metadata_json.items()
                if isinstance(key, str) and isinstance(value, str)
            }
        except SkillNotFoundError:
            raise
        except (OSError, ValueError, ValidationError, SQLAlchemyError) as error:
            raise ApiServiceUnavailableError("Skill detail is unavailable.") from error

        return SkillDetailResponse(
            request_id=request_id,
            skill_id=skill.id,
            name=skill.name,
            description=skill.description,
            path=skill.path,
            source_url=skill.html_url,
            declared_license=skill.declared_license,
            compatibility=skill.compatibility,
            allowed_tools=tuple(skill.allowed_tools),
            metadata=metadata,
            validation_status=skill.validation_status,
            validation_messages=tuple(
                ValidationMessageResponse.model_validate(message.model_dump())
                for message in messages
            ),
            structural_signals=StructuralSignalsResponse(
                has_scripts=skill.has_scripts,
                has_references=skill.has_references,
                has_assets=skill.has_assets,
                script_count=skill.script_count,
                reference_count=skill.reference_count,
                asset_count=skill.asset_count,
                heading_count=skill.heading_count,
                code_block_count=skill.code_block_count,
                external_link_count=skill.external_link_count,
                word_count=skill.word_count,
                byte_count=skill.byte_count,
            ),
            supporting_files=tuple(
                SupportingFileResponse(
                    relative_path=file.relative_path,
                    file_type=file.file_type,
                    size_bytes=file.size_bytes,
                    extension=file.extension,
                )
                for file in files
            ),
            repository=RepositoryDetail(
                full_name=repository.full_name,
                url=repository.html_url,
                default_branch=repository.default_branch,
                stars=repository.stars_count,
                forks=repository.forks_count,
                license_status=repository.license_status,
                license_spdx_id=repository.license_spdx_id,
                license_name=repository.license_name,
            ),
            excerpt=excerpt,
            excerpt_truncated=len(excerpt_source) > MAX_EXCERPT_CHARACTERS,
            first_seen_at=skill.first_seen_at,
            last_seen_at=skill.last_seen_at,
        )

    def stats(self, session: Session, *, request_id: str) -> StatsResponse:
        """Return bounded aggregate evidence for the current database and snapshot."""

        try:
            assets = self._load_assets(session)
            repository_count = int(
                session.scalar(select(func.count()).select_from(Repository)) or 0
            )
            skill_count = int(session.scalar(select(func.count()).select_from(Skill)) or 0)
            validation_rows = session.execute(
                select(Skill.validation_status, func.count(Skill.id)).group_by(
                    Skill.validation_status
                )
            ).all()
            license_rows = session.execute(
                select(Repository.license_status, func.count(Repository.id)).group_by(
                    Repository.license_status
                )
            ).all()
            feature_row = session.execute(
                select(
                    func.count(Skill.id).filter(Skill.has_scripts),
                    func.count(Skill.id).filter(Skill.has_references),
                    func.count(Skill.id).filter(Skill.has_assets),
                )
            ).one()
            tools = Counter(
                normalized
                for allowed_tools in session.scalars(select(Skill.allowed_tools))
                for tool in allowed_tools
                if isinstance(tool, str) and (normalized := _normalize_declared_tool(tool))
            )
            latest_ingestion_at = session.scalar(
                select(func.max(IngestionRun.completed_at)).where(
                    IngestionRun.status == IngestionRunStatus.COMPLETED
                )
            )
        except (OSError, ValueError, SQLAlchemyError) as error:
            raise ApiServiceUnavailableError("Statistics are unavailable.") from error

        validation_statuses = {status: 0 for status in ValidationStatus}
        for validation_status, count in validation_rows:
            validation_statuses[validation_status] = int(count)
        license_statuses = {status: 0 for status in LicenseStatus}
        for license_status, count in license_rows:
            license_statuses[license_status] = int(count)
        common_tools = sorted(tools.items(), key=lambda item: (-item[1], item[0]))

        return StatsResponse(
            request_id=request_id,
            repository_count=repository_count,
            skill_count=skill_count,
            retrieval_eligible_skill_count=len(assets.corpus.documents),
            validation_statuses=validation_statuses,
            license_statuses=license_statuses,
            features=FeatureCounts(
                scripts=int(feature_row[0]),
                references=int(feature_row[1]),
                assets=int(feature_row[2]),
            ),
            common_declared_tools=tuple(
                ToolCount(tool=tool, count=count) for tool, count in common_tools[:MAX_COMMON_TOOLS]
            ),
            latest_ingestion_at=latest_ingestion_at,
            dataset_snapshot=_snapshot_reference(
                assets.corpus,
                path=assets.bm25_config.corpus_snapshot_path,
            ),
        )

    def latest_evaluation(self, *, request_id: str) -> LatestEvaluationResponse:
        """Read the canonical immutable test report and expose only aggregate evidence."""

        try:
            serialized = self.evaluation_report_path.read_bytes()
            if not serialized or len(serialized) > MAX_EVALUATION_REPORT_BYTES:
                raise ValueError("evaluation report has an invalid size")
            report = RetrievalComparisonReport.model_validate(json.loads(serialized))
            if report.split.value != "test":
                raise ValueError("latest evaluation report is not the frozen test split")
            dense_config = load_dense_hybrid_config(self.dense_config_path)
            if report.corpus_snapshot_sha256 != dense_config.corpus_snapshot_sha256:
                raise ValueError("evaluation report and retrieval configuration differ")
        except (OSError, ValueError, ValidationError, json.JSONDecodeError) as error:
            raise ApiServiceUnavailableError("Evaluation evidence is unavailable.") from error

        methods = tuple(
            EvaluationMetrics(
                method=method.method,
                query_count=method.query_count,
                ndcg_at_10=method.ndcg_at_10,
                mrr_at_10=method.mrr_at_10,
                recall_at_10=method.recall_at_10,
                latency=EvaluationLatency(
                    p50_ms=method.latency.p50_ms,
                    p95_ms=method.latency.p95_ms,
                    sample_count=method.latency.sample_count,
                ),
            )
            for method in report.methods
        )
        return LatestEvaluationResponse(
            request_id=request_id,
            generated_at=report.generated_at,
            git_commit=report.git_commit,
            split="test",
            report_sha256=hashlib.sha256(serialized).hexdigest(),
            dataset_snapshot=DatasetSnapshotReference(
                path=dense_config.corpus_snapshot_path,
                sha256=report.corpus_snapshot_sha256,
            ),
            configuration=EvaluationConfiguration(
                model_id=report.model_id,
                model_revision=report.model_revision,
                model_dimension=report.model_dimension,
                exact_dense_search=report.exact_dense_search,
                rrf_candidate_depth=report.rrf_candidate_depth,
                rrf_k=report.rrf_k,
                bm25_weight=report.bm25_weight,
                dense_weight=report.dense_weight,
                cutoff=report.cutoff,
            ),
            methods=(methods[0], methods[1], methods[2]),
        )

    def _load_assets(self, session: Session) -> RetrievalAssets:
        """Reconcile the frozen corpus, reusing the last build while it is current.

        Rebuilding tokenizes every document, so a serving process caches the
        result. The cache key covers both configuration bytes, the snapshot
        bytes, and a stored-skill fingerprint, so any drift still forces the
        full reconciling rebuild that would have rejected it.
        """

        bm25_config = load_bm25_config(self.bm25_config_path)
        dense_config = load_dense_hybrid_config(self.dense_config_path)
        dense_config_sha256 = hashlib.sha256(self.dense_config_path.read_bytes()).hexdigest()
        bm25_config_sha256 = hashlib.sha256(self.bm25_config_path.read_bytes()).hexdigest()
        if dense_config.corpus_snapshot_sha256 != bm25_config.corpus_snapshot_sha256:
            raise ValueError("retrieval configurations use different snapshots")
        if bm25_config_sha256 != dense_config.bm25_config_sha256:
            raise ValueError("dense configuration references different BM25 bytes")

        fingerprint = AssetsFingerprint(
            bm25_config_sha256=bm25_config_sha256,
            dense_config_sha256=dense_config_sha256,
            snapshot_sha256=bm25_config.corpus_snapshot_sha256,
            stored_skills=stored_skill_fingerprint(session),
        )
        with self._assets_lock:
            cached = self._cached_assets
        if cached is not None and cached[0] == fingerprint:
            return cached[1]

        snapshot_path = self._project_path(
            bm25_config.corpus_snapshot_path,
            suffix=".jsonl",
        )
        corpus = load_frozen_corpus(
            session,
            bm25_config,
            snapshot_path=snapshot_path,
            project_root=self.project_root,
        )
        assets = RetrievalAssets(
            bm25_config=bm25_config,
            dense_config=dense_config,
            dense_config_sha256=dense_config_sha256,
            corpus=corpus,
            bm25=BM25Index(corpus, bm25_config),
        )
        with self._assets_lock:
            self._cached_assets = (fingerprint, assets)
        return assets

    def _attach_search_metadata(
        self,
        session: Session,
        ranked: tuple[RankedApiResult, ...],
    ) -> tuple[SearchResult, ...]:
        skill_ids = tuple(item[0] for item in ranked)
        if not skill_ids:
            return ()
        rows = session.execute(
            select(Skill, Repository)
            .join(Repository, Skill.repository_id == Repository.id)
            .where(Skill.id.in_(skill_ids))
        ).all()
        metadata = {skill.id: (skill, repository) for skill, repository in rows}
        if set(metadata) != set(skill_ids):
            raise ValueError("ranked skills changed before response metadata was loaded")

        return tuple(
            SearchResult(
                rank=rank,
                skill_id=skill_id,
                name=metadata[skill_id][0].name,
                description=metadata[skill_id][0].description,
                snippet=metadata[skill_id][0].safe_snippet[:MAX_SAFE_SNIPPET_CHARACTERS],
                repository=RepositorySummary(
                    full_name=metadata[skill_id][1].full_name,
                    url=metadata[skill_id][1].html_url,
                    stars=metadata[skill_id][1].stars_count,
                    license_status=metadata[skill_id][1].license_status,
                ),
                path=metadata[skill_id][0].path,
                source_url=metadata[skill_id][0].html_url,
                validation_status=metadata[skill_id][0].validation_status,
                has_scripts=metadata[skill_id][0].has_scripts,
                score=score,
                score_components=components,
            )
            for rank, (skill_id, score, components) in enumerate(ranked, start=1)
        )

    @staticmethod
    def _bm25_results(
        results: tuple[BM25Result, ...],
    ) -> tuple[tuple[UUID, float, BM25ScoreComponents], ...]:
        return tuple(
            (
                result.document.skill_id,
                result.score,
                BM25ScoreComponents(
                    matched_terms=result.matched_terms,
                    term_contributions=tuple(
                        BM25TermContribution(
                            term=item.term,
                            term_frequency=item.term_frequency,
                            document_frequency=item.document_frequency,
                            inverse_document_frequency=item.inverse_document_frequency,
                            score=item.score,
                        )
                        for item in result.term_scores
                    ),
                ),
            )
            for result in results
        )

    @staticmethod
    def _dense_results(
        results: tuple[DenseResult, ...],
    ) -> tuple[tuple[UUID, float, DenseScoreComponents], ...]:
        return tuple(
            (
                result.document.skill_id,
                result.cosine_similarity,
                DenseScoreComponents(
                    cosine_similarity=result.cosine_similarity,
                    cosine_distance=result.cosine_distance,
                ),
            )
            for result in results
        )

    @staticmethod
    def _hybrid_results(
        results: tuple[HybridResult, ...],
    ) -> tuple[tuple[UUID, float, HybridScoreComponents], ...]:
        return tuple(
            (
                result.document.skill_id,
                result.fused_score,
                HybridScoreComponents(
                    rrf_score=result.fused_score,
                    bm25_rank=result.bm25_rank,
                    dense_rank=result.dense_rank,
                    bm25_score=result.bm25_score,
                    dense_similarity=result.dense_similarity,
                ),
            )
            for result in results
        )

    def _project_path(self, value: str, *, suffix: str) -> Path:
        path = Path(value)
        if (
            path.is_absolute()
            or path.suffix != suffix
            or ".." in path.parts
            or path.as_posix() != value
        ):
            raise ValueError("API evidence paths must be normalized project-relative paths")
        resolved = (self.project_root / path).resolve()
        if not resolved.is_relative_to(self.project_root):
            raise ValueError("API evidence path leaves the project root")
        return resolved


def _snapshot_reference(
    corpus: FrozenCorpus,
    *,
    path: str,
) -> DatasetSnapshotReference:
    return DatasetSnapshotReference(
        path=path,
        sha256=corpus.snapshot_sha256,
    )


def _normalize_declared_tool(value: str) -> str:
    """Fold one stored `allowed-tools` token into a comparable display name.

    The parser splits the field on whitespace because the specification calls it
    space separated, so authors who write `Read, Grep` leave separator
    characters attached. Those are stripped here, for aggregate display only,
    rather than in the parser where they would alter stored evidence.
    """

    return value.strip().strip(",;").strip().casefold()


def _plain_text(value: str) -> str:
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        character
        for character in normalized
        if character in {"\n", "\t"} or not unicodedata.category(character).startswith("C")
    ).strip()


def _score_semantics(mode: RetrievalMethod) -> str:
    if mode is RetrievalMethod.BM25:
        return "BM25 lexical score; compare only within this response."
    if mode is RetrievalMethod.DENSE:
        return "Exact cosine similarity; compare only within this response."
    return "Reciprocal-rank-fusion score; source ranks are explanatory, not raw-score sums."
