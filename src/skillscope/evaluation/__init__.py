"""Frozen query, qrel, pooling, and metric primitives."""

from skillscope.evaluation.config import EvaluationConfig, load_evaluation_config
from skillscope.evaluation.data import (
    EvaluationDataError,
    EvaluationQueryRecord,
    QrelRecord,
    QrelSet,
    QuerySet,
    read_qrel_set,
    read_query_set,
    validate_evaluation_dataset,
)
from skillscope.evaluation.metrics import (
    AggregateMetrics,
    QueryMetrics,
    discounted_cumulative_gain,
    evaluate_rankings,
    ndcg_at_k,
    recall_at_k,
    reciprocal_rank_at_k,
)
from skillscope.evaluation.pooling import (
    CandidatePool,
    build_bm25_candidate_pool,
    qrels_from_label_worksheet,
    read_candidate_pool,
    write_candidate_pool,
    write_label_worksheet,
)
from skillscope.evaluation.runner import (
    BM25EvaluationReport,
    TestSplitLockedError,
    evaluate_bm25,
    write_evaluation_report,
)

__all__ = [
    "AggregateMetrics",
    "BM25EvaluationReport",
    "CandidatePool",
    "EvaluationConfig",
    "EvaluationDataError",
    "EvaluationQueryRecord",
    "QrelRecord",
    "QrelSet",
    "QueryMetrics",
    "QuerySet",
    "TestSplitLockedError",
    "build_bm25_candidate_pool",
    "discounted_cumulative_gain",
    "evaluate_bm25",
    "evaluate_rankings",
    "load_evaluation_config",
    "ndcg_at_k",
    "qrels_from_label_worksheet",
    "read_candidate_pool",
    "read_qrel_set",
    "read_query_set",
    "recall_at_k",
    "reciprocal_rank_at_k",
    "validate_evaluation_dataset",
    "write_candidate_pool",
    "write_evaluation_report",
    "write_label_worksheet",
]
