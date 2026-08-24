"""BM25 evaluation against frozen queries and graded qrels."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from skillscope.db.enums import EvaluationSplit
from skillscope.evaluation.data import QrelSet, QuerySet, Sha256
from skillscope.evaluation.metrics import evaluate_rankings
from skillscope.retrieval.bm25 import BM25Index


class TestSplitLockedError(ValueError):
    """The frozen test split was requested before the final comparison gate."""

    __test__ = False


type FailureType = Literal[
    "no_relevant_result_in_top_10",
    "first_relevant_result_below_rank_3",
    "relevant_pool_items_missed",
    "relative_ordering_error",
]


class ReportRecord(BaseModel):
    """Strict immutable base for evaluation report records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RankedEvaluationResult(ReportRecord):
    """Safe ranked metadata and its judged grade."""

    rank: int = Field(ge=1, le=100)
    document_id: str
    repository: str
    path: str
    name: str
    score: float = Field(ge=0.0)
    relevance: int = Field(ge=0, le=2)


class PerQueryEvaluation(ReportRecord):
    """One query's metrics and top-ranked safe evidence."""

    query_id: str
    query_text: str
    category: str
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    reciprocal_rank_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    relevant_count: int = Field(ge=1)
    relevant_retrieved: int = Field(ge=0)
    results: tuple[RankedEvaluationResult, ...]


class FailureExample(ReportRecord):
    """Deterministically selected low-performing development query."""

    query_id: str
    query_text: str
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    reciprocal_rank_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    failure_type: FailureType


class BM25EvaluationReport(ReportRecord):
    """Canonical metrics and failure evidence for one frozen BM25 run."""

    schema_version: Literal[1] = 1
    report_type: Literal["retrieval_evaluation"] = "retrieval_evaluation"
    generated_at: datetime
    git_commit: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    method: Literal["bm25"] = "bm25"
    split: EvaluationSplit
    corpus_snapshot_sha256: Sha256
    query_set_sha256: Sha256
    qrels_sha256: Sha256
    bm25_config_sha256: Sha256
    k1: float = Field(gt=0.0)
    b: float = Field(ge=0.0, le=1.0)
    cutoff: Literal[10] = 10
    query_count: int = Field(ge=1, le=30)
    ndcg_at_10: float = Field(ge=0.0, le=1.0)
    mrr_at_10: float = Field(ge=0.0, le=1.0)
    recall_at_10: float = Field(ge=0.0, le=1.0)
    queries: tuple[PerQueryEvaluation, ...]
    failure_examples: tuple[FailureExample, ...]

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must include a timezone")
        return value


def evaluate_bm25(
    index: BM25Index,
    query_set: QuerySet,
    qrels: QrelSet,
    *,
    split: EvaluationSplit,
    generated_at: datetime,
    git_commit: str,
    query_set_sha256: str,
    qrels_sha256: str,
    bm25_config_sha256: str,
    allow_test: bool = False,
) -> BM25EvaluationReport:
    """Evaluate one split, with the test split locked unless explicitly released."""

    if split is EvaluationSplit.TEST and not allow_test:
        raise TestSplitLockedError(
            "test metrics are locked until the final Milestone 8 method comparison"
        )
    if index.snapshot_sha256 != query_set.header.corpus_snapshot_sha256:
        raise ValueError("BM25 index and query set use different corpus snapshots")

    relevance_by_query: dict[str, dict[str, int]] = {}
    for judgement in qrels.judgements:
        relevance_by_query.setdefault(judgement.query_id, {})[judgement.document_id] = (
            judgement.relevance
        )

    selected_queries = tuple(query for query in query_set.queries if query.split is split)
    if not selected_queries:
        raise ValueError(f"query set contains no {split.value} queries")
    rankings: dict[str, tuple[str, ...]] = {}
    raw_results = {}
    for query in selected_queries:
        results = index.search(query.query_text, top_k=10)
        raw_results[query.query_id] = results
        rankings[query.query_id] = tuple(result.document.document_id for result in results)

    selected_qrels = {
        query.query_id: relevance_by_query[query.query_id] for query in selected_queries
    }
    metrics = evaluate_rankings(
        rankings,
        selected_qrels,
        cutoff=10,
        relevance_threshold=qrels.header.relevance_threshold,
    )
    metrics_by_query = {item.query_id: item for item in metrics.per_query}
    per_query: list[PerQueryEvaluation] = []
    for query in selected_queries:
        query_metrics = metrics_by_query[query.query_id]
        query_relevance = selected_qrels[query.query_id]
        per_query.append(
            PerQueryEvaluation(
                query_id=query.query_id,
                query_text=query.query_text,
                category=query.category,
                ndcg_at_10=query_metrics.ndcg,
                reciprocal_rank_at_10=query_metrics.reciprocal_rank,
                recall_at_10=query_metrics.recall,
                relevant_count=query_metrics.relevant_count,
                relevant_retrieved=query_metrics.relevant_retrieved,
                results=tuple(
                    RankedEvaluationResult(
                        rank=rank,
                        document_id=result.document.document_id,
                        repository=result.document.repository_full_name,
                        path=result.document.path,
                        name=result.document.name,
                        score=result.score,
                        relevance=query_relevance.get(result.document.document_id, 0),
                    )
                    for rank, result in enumerate(raw_results[query.query_id], start=1)
                ),
            )
        )

    return BM25EvaluationReport(
        generated_at=generated_at,
        git_commit=git_commit,
        split=split,
        corpus_snapshot_sha256=index.snapshot_sha256,
        query_set_sha256=query_set_sha256,
        qrels_sha256=qrels_sha256,
        bm25_config_sha256=bm25_config_sha256,
        k1=index.config.k1,
        b=index.config.b,
        query_count=metrics.query_count,
        ndcg_at_10=metrics.ndcg,
        mrr_at_10=metrics.mrr,
        recall_at_10=metrics.recall,
        queries=tuple(per_query),
        failure_examples=_failure_examples(tuple(per_query)),
    )


def serialize_evaluation_report(report: BM25EvaluationReport) -> bytes:
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


def write_evaluation_report(path: Path, report: BM25EvaluationReport) -> None:
    """Atomically write a canonical JSON report to a safe relative path."""

    _validate_report_path(path)
    serialized = serialize_evaluation_report(report)
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


def _failure_examples(
    queries: tuple[PerQueryEvaluation, ...],
    *,
    limit: int = 3,
) -> tuple[FailureExample, ...]:
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
        FailureExample(
            query_id=query.query_id,
            query_text=query.query_text,
            ndcg_at_10=query.ndcg_at_10,
            reciprocal_rank_at_10=query.reciprocal_rank_at_10,
            recall_at_10=query.recall_at_10,
            failure_type=_failure_type(query),
        )
        for query in ranked[:limit]
    )


def _failure_type(query: PerQueryEvaluation) -> FailureType:
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
        raise ValueError("evaluation report path must be a safe relative JSON path")
