"""Auditable ranking metrics for graded SkillScope relevance judgements."""

from __future__ import annotations

import math
from dataclasses import dataclass

DEFAULT_METRIC_CUTOFF = 10


@dataclass(frozen=True, slots=True)
class QueryMetrics:
    """Metric values for one query at one cutoff."""

    query_id: str
    ndcg: float
    reciprocal_rank: float
    recall: float
    relevant_count: int
    relevant_retrieved: int


@dataclass(frozen=True, slots=True)
class AggregateMetrics:
    """Macro averages plus immutable per-query evidence."""

    cutoff: int
    query_count: int
    ndcg: float
    mrr: float
    recall: float
    per_query: tuple[QueryMetrics, ...]


def discounted_cumulative_gain(relevances: tuple[int, ...], *, cutoff: int) -> float:
    """Return DCG using exponential gain and log2 rank discount."""

    _validate_cutoff(cutoff)
    _validate_relevances(relevances)
    return math.fsum(
        (2**relevance - 1) / math.log2(rank + 1)
        for rank, relevance in enumerate(relevances[:cutoff], start=1)
    )


def ndcg_at_k(
    ranked_document_ids: tuple[str, ...],
    relevance_by_document: dict[str, int],
    *,
    cutoff: int = DEFAULT_METRIC_CUTOFF,
) -> float:
    """Return normalized DCG, treating unjudged retrieved documents as non-relevant."""

    _validate_ranking(ranked_document_ids)
    _validate_relevances(tuple(relevance_by_document.values()))
    actual = tuple(relevance_by_document.get(document_id, 0) for document_id in ranked_document_ids)
    ideal = tuple(sorted(relevance_by_document.values(), reverse=True))
    ideal_dcg = discounted_cumulative_gain(ideal, cutoff=cutoff)
    if ideal_dcg == 0.0:
        return 0.0
    return discounted_cumulative_gain(actual, cutoff=cutoff) / ideal_dcg


def reciprocal_rank_at_k(
    ranked_document_ids: tuple[str, ...],
    relevance_by_document: dict[str, int],
    *,
    cutoff: int = DEFAULT_METRIC_CUTOFF,
    relevance_threshold: int = 1,
) -> float:
    """Return the reciprocal rank of the first relevant result within the cutoff."""

    _validate_cutoff(cutoff)
    _validate_threshold(relevance_threshold)
    _validate_ranking(ranked_document_ids)
    _validate_relevances(tuple(relevance_by_document.values()))
    for rank, document_id in enumerate(ranked_document_ids[:cutoff], start=1):
        if relevance_by_document.get(document_id, 0) >= relevance_threshold:
            return 1.0 / rank
    return 0.0


def recall_at_k(
    ranked_document_ids: tuple[str, ...],
    relevance_by_document: dict[str, int],
    *,
    cutoff: int = DEFAULT_METRIC_CUTOFF,
    relevance_threshold: int = 1,
) -> float:
    """Return judged relevant documents retrieved divided by all judged relevant documents."""

    _validate_cutoff(cutoff)
    _validate_threshold(relevance_threshold)
    _validate_ranking(ranked_document_ids)
    _validate_relevances(tuple(relevance_by_document.values()))
    relevant = {
        document_id
        for document_id, relevance in relevance_by_document.items()
        if relevance >= relevance_threshold
    }
    if not relevant:
        return 0.0
    retrieved = set(ranked_document_ids[:cutoff])
    return len(relevant & retrieved) / len(relevant)


def evaluate_rankings(
    rankings: dict[str, tuple[str, ...]],
    qrels: dict[str, dict[str, int]],
    *,
    cutoff: int = DEFAULT_METRIC_CUTOFF,
    relevance_threshold: int = 1,
) -> AggregateMetrics:
    """Evaluate exact query rankings and return deterministic macro averages."""

    _validate_cutoff(cutoff)
    _validate_threshold(relevance_threshold)
    if not rankings:
        raise ValueError("at least one query ranking is required")
    if set(rankings) != set(qrels):
        raise ValueError("rankings and qrels must contain the same query IDs")

    per_query: list[QueryMetrics] = []
    for query_id in sorted(rankings):
        ranking = rankings[query_id]
        relevance_by_document = qrels[query_id]
        relevant_count = sum(
            relevance >= relevance_threshold for relevance in relevance_by_document.values()
        )
        if relevant_count == 0:
            raise ValueError(f"query {query_id} has no relevant judgements")
        retrieved_ids = set(ranking[:cutoff])
        relevant_retrieved = sum(
            document_id in retrieved_ids and relevance >= relevance_threshold
            for document_id, relevance in relevance_by_document.items()
        )
        per_query.append(
            QueryMetrics(
                query_id=query_id,
                ndcg=ndcg_at_k(ranking, relevance_by_document, cutoff=cutoff),
                reciprocal_rank=reciprocal_rank_at_k(
                    ranking,
                    relevance_by_document,
                    cutoff=cutoff,
                    relevance_threshold=relevance_threshold,
                ),
                recall=recall_at_k(
                    ranking,
                    relevance_by_document,
                    cutoff=cutoff,
                    relevance_threshold=relevance_threshold,
                ),
                relevant_count=relevant_count,
                relevant_retrieved=relevant_retrieved,
            )
        )

    query_count = len(per_query)
    return AggregateMetrics(
        cutoff=cutoff,
        query_count=query_count,
        ndcg=sum(item.ndcg for item in per_query) / query_count,
        mrr=sum(item.reciprocal_rank for item in per_query) / query_count,
        recall=sum(item.recall for item in per_query) / query_count,
        per_query=tuple(per_query),
    )


def _validate_cutoff(cutoff: int) -> None:
    if not 1 <= cutoff <= 100:
        raise ValueError("metric cutoff must be between 1 and 100")


def _validate_threshold(relevance_threshold: int) -> None:
    if not 1 <= relevance_threshold <= 2:
        raise ValueError("relevance threshold must be 1 or 2")


def _validate_relevances(relevances: tuple[int, ...]) -> None:
    if any(relevance < 0 or relevance > 2 for relevance in relevances):
        raise ValueError("relevance grades must be between 0 and 2")


def _validate_ranking(ranked_document_ids: tuple[str, ...]) -> None:
    if len(set(ranked_document_ids)) != len(ranked_document_ids):
        raise ValueError("rankings cannot contain duplicate document IDs")
