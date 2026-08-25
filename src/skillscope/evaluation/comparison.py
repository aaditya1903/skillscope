"""BM25, exact dense, and RRF hybrid evaluation on one frozen split."""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter_ns
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from skillscope.db.enums import EvaluationSplit, RetrievalMethod
from skillscope.evaluation.data import EvaluationQueryRecord, QrelSet, QuerySet, Sha256
from skillscope.evaluation.metrics import evaluate_rankings
from skillscope.evaluation.runner import FailureType, TestSplitLockedError
from skillscope.retrieval.bm25 import BM25Index
from skillscope.retrieval.config import DenseHybridConfig
from skillscope.retrieval.corpus import CorpusDocument
from skillscope.retrieval.dense import DenseRetriever
from skillscope.retrieval.hybrid import HybridRetriever

WARMUP_QUERY = "semantic retrieval warmup"


@dataclass(frozen=True, slots=True)
class EvaluationHit:
    """One method-independent ranked result used by the evaluator."""

    document: CorpusDocument
    score: float
    score_label: Literal["bm25", "cosine_similarity", "rrf"]
    bm25_rank: int | None = None
    dense_rank: int | None = None
    bm25_score: float | None = None
    dense_similarity: float | None = None


class EvaluationRetriever(Protocol):
    """Search boundary shared by all evaluated retrieval methods."""

    method: RetrievalMethod
    snapshot_sha256: str

    def search(self, query: str, *, top_k: int) -> tuple[EvaluationHit, ...]:
        """Return at most top_k safe ranked results."""


class BM25EvaluationRetriever:
    """Adapt the transparent BM25 index to the comparison boundary."""

    method = RetrievalMethod.BM25

    def __init__(self, index: BM25Index) -> None:
        self.index = index
        self.snapshot_sha256 = index.snapshot_sha256

    def search(self, query: str, *, top_k: int) -> tuple[EvaluationHit, ...]:
        return tuple(
            EvaluationHit(
                document=result.document,
                score=result.score,
                score_label="bm25",
                bm25_rank=rank,
                bm25_score=result.score,
            )
            for rank, result in enumerate(self.index.search(query, top_k=top_k), start=1)
        )


class DenseEvaluationRetriever:
    """Adapt exact cosine retrieval to the comparison boundary."""

    method = RetrievalMethod.DENSE

    def __init__(self, retriever: DenseRetriever) -> None:
        self.retriever = retriever
        self.snapshot_sha256 = retriever.corpus.snapshot_sha256

    def search(self, query: str, *, top_k: int) -> tuple[EvaluationHit, ...]:
        return tuple(
            EvaluationHit(
                document=result.document,
                score=result.cosine_similarity,
                score_label="cosine_similarity",
                dense_rank=rank,
                dense_similarity=result.cosine_similarity,
            )
            for rank, result in enumerate(self.retriever.search(query, top_k=top_k), start=1)
        )


class HybridEvaluationRetriever:
    """Adapt RRF results while preserving both contributing ranks."""

    method = RetrievalMethod.HYBRID

    def __init__(self, retriever: HybridRetriever) -> None:
        self.retriever = retriever
        self.snapshot_sha256 = retriever.bm25.snapshot_sha256

    def search(self, query: str, *, top_k: int) -> tuple[EvaluationHit, ...]:
        return tuple(
            EvaluationHit(
                document=result.document,
                score=result.fused_score,
                score_label="rrf",
                bm25_rank=result.bm25_rank,
                dense_rank=result.dense_rank,
                bm25_score=result.bm25_score,
                dense_similarity=result.dense_similarity,
            )
            for result in self.retriever.search(query, top_k=top_k)
        )


class ComparisonRecord(BaseModel):
    """Strict immutable base for final retrieval-comparison evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ComparisonRankedResult(ComparisonRecord):
    """Safe ranked metadata, score semantics, source ranks, and judged grade."""

    rank: int = Field(ge=1, le=100)
    document_id: str
    repository: str
    path: str
    name: str
    score: float
    score_label: Literal["bm25", "cosine_similarity", "rrf"]
    relevance: int = Field(ge=0, le=2)
    bm25_rank: int | None = Field(default=None, ge=1, le=100)
    dense_rank: int | None = Field(default=None, ge=1, le=100)
    bm25_score: float | None = None
    dense_similarity: float | None = Field(default=None, ge=-1.0, le=1.0)


class ComparisonQueryResult(ComparisonRecord):
    """One query's metrics and top-ranked result evidence for one method."""

    query_id: str
    query_text: str
    category: str
    latency_ms: float = Field(ge=0.0)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    reciprocal_rank_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    relevant_count: int = Field(ge=1)
    relevant_retrieved: int = Field(ge=0)
    results: tuple[ComparisonRankedResult, ...]


class ComparisonFailureExample(ComparisonRecord):
    """Deterministically selected failure evidence for one method."""

    query_id: str
    query_text: str
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    reciprocal_rank_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    failure_type: FailureType


class LatencySummary(ComparisonRecord):
    """Nearest-rank latency percentiles after an unmeasured warm-up query."""

    warmup_count: Literal[1] = 1
    sample_count: int = Field(ge=1)
    p50_ms: float = Field(ge=0.0)
    p95_ms: float = Field(ge=0.0)


class MethodComparison(ComparisonRecord):
    """Aggregate and per-query evidence for one retrieval method."""

    method: RetrievalMethod
    query_count: int = Field(ge=1, le=30)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    mrr_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    latency: LatencySummary
    queries: tuple[ComparisonQueryResult, ...]
    failure_examples: tuple[ComparisonFailureExample, ...]


class RetrievalComparisonReport(ComparisonRecord):
    """Canonical same-snapshot evidence for BM25, dense, and hybrid retrieval."""

    schema_version: Literal[1] = 1
    report_type: Literal["retrieval_method_comparison"] = "retrieval_method_comparison"
    generated_at: datetime
    git_commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    split: EvaluationSplit
    corpus_snapshot_sha256: Sha256
    query_set_sha256: Sha256
    qrels_sha256: Sha256
    evaluation_config_sha256: Sha256
    bm25_config_sha256: Sha256
    dense_hybrid_config_sha256: Sha256
    model_id: str
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    model_dimension: Literal[384] = 384
    normalized_embeddings: Literal[True] = True
    exact_dense_search: Literal[True] = True
    rrf_candidate_depth: Literal[50] = 50
    rrf_k: Literal[60] = 60
    bm25_weight: float = Field(gt=0.0)
    dense_weight: float = Field(gt=0.0)
    cutoff: Literal[10] = 10
    methods: tuple[MethodComparison, MethodComparison, MethodComparison]

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_method_order(self) -> RetrievalComparisonReport:
        if tuple(method.method for method in self.methods) != (
            RetrievalMethod.BM25,
            RetrievalMethod.DENSE,
            RetrievalMethod.HYBRID,
        ):
            raise ValueError("comparison methods must be ordered BM25, dense, hybrid")
        return self


def evaluate_retrieval_methods(
    retrievers: tuple[EvaluationRetriever, EvaluationRetriever, EvaluationRetriever],
    query_set: QuerySet,
    qrels: QrelSet,
    dense_config: DenseHybridConfig,
    *,
    split: EvaluationSplit,
    generated_at: datetime,
    git_commit: str,
    query_set_sha256: str,
    qrels_sha256: str,
    evaluation_config_sha256: str,
    bm25_config_sha256: str,
    dense_hybrid_config_sha256: str,
    allow_test: bool = False,
) -> RetrievalComparisonReport:
    """Evaluate all methods, with the frozen test split locked by default."""

    if split is EvaluationSplit.TEST and not allow_test:
        raise TestSplitLockedError(
            "test metrics are locked until the final frozen method comparison"
        )
    expected_methods = (
        RetrievalMethod.BM25,
        RetrievalMethod.DENSE,
        RetrievalMethod.HYBRID,
    )
    if tuple(retriever.method for retriever in retrievers) != expected_methods:
        raise ValueError("retrievers must be ordered BM25, dense, hybrid")
    if any(
        retriever.snapshot_sha256 != query_set.header.corpus_snapshot_sha256
        for retriever in retrievers
    ):
        raise ValueError("all retrievers must use the query set's frozen corpus snapshot")

    selected_queries = tuple(query for query in query_set.queries if query.split is split)
    if not selected_queries:
        raise ValueError(f"query set contains no {split.value} queries")
    relevance_by_query: dict[str, dict[str, int]] = {}
    for judgement in qrels.judgements:
        relevance_by_query.setdefault(judgement.query_id, {})[judgement.document_id] = (
            judgement.relevance
        )

    methods = tuple(
        _evaluate_method(
            retriever,
            selected_queries=selected_queries,
            relevance_by_query=relevance_by_query,
            relevance_threshold=qrels.header.relevance_threshold,
        )
        for retriever in retrievers
    )
    return RetrievalComparisonReport(
        generated_at=generated_at,
        git_commit=git_commit,
        split=split,
        corpus_snapshot_sha256=query_set.header.corpus_snapshot_sha256,
        query_set_sha256=query_set_sha256,
        qrels_sha256=qrels_sha256,
        evaluation_config_sha256=evaluation_config_sha256,
        bm25_config_sha256=bm25_config_sha256,
        dense_hybrid_config_sha256=dense_hybrid_config_sha256,
        model_id=dense_config.model_id,
        model_revision=dense_config.model_revision,
        model_dimension=dense_config.model_dimension,
        normalized_embeddings=dense_config.normalize_embeddings,
        exact_dense_search=dense_config.exact_search,
        rrf_candidate_depth=dense_config.rrf_candidate_depth,
        rrf_k=dense_config.rrf_k,
        bm25_weight=dense_config.bm25_weight,
        dense_weight=dense_config.dense_weight,
        methods=(methods[0], methods[1], methods[2]),
    )


def serialize_comparison_report(report: RetrievalComparisonReport) -> bytes:
    """Return canonical UTF-8 JSON with a required final newline."""

    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def write_comparison_report(
    path: Path,
    report: RetrievalComparisonReport,
    *,
    refuse_overwrite: bool = False,
) -> None:
    """Atomically write comparison evidence, optionally enforcing a one-time release."""

    _validate_report_path(path)
    if refuse_overwrite and path.exists():
        raise ValueError("the frozen test comparison report already exists")
    serialized = serialize_comparison_report(report)
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
        if refuse_overwrite:
            try:
                os.link(temporary_path, path)
            except FileExistsError as error:
                raise ValueError("the frozen test comparison report already exists") from error
            temporary_path.unlink()
            temporary_path = None
        else:
            os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _evaluate_method(
    retriever: EvaluationRetriever,
    *,
    selected_queries: tuple[EvaluationQueryRecord, ...],
    relevance_by_query: dict[str, dict[str, int]],
    relevance_threshold: int,
) -> MethodComparison:
    retriever.search(WARMUP_QUERY, top_k=10)
    rankings: dict[str, tuple[str, ...]] = {}
    raw_results: dict[str, tuple[EvaluationHit, ...]] = {}
    latency_by_query: dict[str, float] = {}
    for query in selected_queries:
        started_at = perf_counter_ns()
        results = retriever.search(query.query_text, top_k=10)
        elapsed_ms = (perf_counter_ns() - started_at) / 1_000_000.0
        raw_results[query.query_id] = results
        latency_by_query[query.query_id] = elapsed_ms
        rankings[query.query_id] = tuple(result.document.document_id for result in results)

    selected_qrels = {
        query.query_id: relevance_by_query[query.query_id] for query in selected_queries
    }
    metrics = evaluate_rankings(
        rankings,
        selected_qrels,
        cutoff=10,
        relevance_threshold=relevance_threshold,
    )
    metrics_by_query = {item.query_id: item for item in metrics.per_query}
    query_results: list[ComparisonQueryResult] = []
    for query in selected_queries:
        query_metrics = metrics_by_query[query.query_id]
        query_relevance = selected_qrels[query.query_id]
        query_results.append(
            ComparisonQueryResult(
                query_id=query.query_id,
                query_text=query.query_text,
                category=query.category,
                latency_ms=latency_by_query[query.query_id],
                ndcg_at_10=query_metrics.ndcg,
                reciprocal_rank_at_10=query_metrics.reciprocal_rank,
                recall_at_10=query_metrics.recall,
                relevant_count=query_metrics.relevant_count,
                relevant_retrieved=query_metrics.relevant_retrieved,
                results=tuple(
                    ComparisonRankedResult(
                        rank=rank,
                        document_id=result.document.document_id,
                        repository=result.document.repository_full_name,
                        path=result.document.path,
                        name=result.document.name,
                        score=result.score,
                        score_label=result.score_label,
                        relevance=query_relevance.get(result.document.document_id, 0),
                        bm25_rank=result.bm25_rank,
                        dense_rank=result.dense_rank,
                        bm25_score=result.bm25_score,
                        dense_similarity=result.dense_similarity,
                    )
                    for rank, result in enumerate(raw_results[query.query_id], start=1)
                ),
            )
        )

    latency_samples = tuple(latency_by_query[query.query_id] for query in selected_queries)
    return MethodComparison(
        method=retriever.method,
        query_count=metrics.query_count,
        ndcg_at_10=metrics.ndcg,
        mrr_at_10=metrics.mrr,
        recall_at_10=metrics.recall,
        latency=LatencySummary(
            sample_count=len(latency_samples),
            p50_ms=_nearest_rank_percentile(latency_samples, 0.50),
            p95_ms=_nearest_rank_percentile(latency_samples, 0.95),
        ),
        queries=tuple(query_results),
        failure_examples=_failure_examples(tuple(query_results)),
    )


def _nearest_rank_percentile(values: tuple[float, ...], percentile: float) -> float:
    if not values:
        raise ValueError("latency percentile requires at least one sample")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _failure_examples(
    queries: tuple[ComparisonQueryResult, ...],
    *,
    limit: int = 3,
) -> tuple[ComparisonFailureExample, ...]:
    ranked = sorted(
        (
            query
            for query in queries
            if query.ndcg_at_10 < 1.0
            or query.reciprocal_rank_at_10 < 1.0
            or query.recall_at_10 < 1.0
        ),
        key=lambda query: (
            query.ndcg_at_10,
            query.reciprocal_rank_at_10,
            query.recall_at_10,
            query.query_id,
        ),
    )
    return tuple(
        ComparisonFailureExample(
            query_id=query.query_id,
            query_text=query.query_text,
            ndcg_at_10=query.ndcg_at_10,
            reciprocal_rank_at_10=query.reciprocal_rank_at_10,
            recall_at_10=query.recall_at_10,
            failure_type=_failure_type(query),
        )
        for query in ranked[:limit]
    )


def _failure_type(query: ComparisonQueryResult) -> FailureType:
    first_relevant_rank = next(
        (result.rank for result in query.results if result.relevance >= 1),
        None,
    )
    if first_relevant_rank is None:
        return "no_relevant_result_in_top_10"
    if first_relevant_rank > 3:
        return "first_relevant_result_below_rank_3"
    if query.recall_at_10 < 1.0:
        return "relevant_pool_items_missed"
    return "relative_ordering_error"


def _validate_report_path(path: Path) -> None:
    value = path.as_posix()
    if (
        path.is_absolute()
        or path.suffix != ".json"
        or ".." in path.parts
        or not value
        or value.startswith("./")
    ):
        raise ValueError("comparison report path must be a safe relative JSON path")
