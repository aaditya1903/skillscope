"""Deterministic reciprocal-rank fusion over BM25 and dense rankings."""

from __future__ import annotations

from dataclasses import dataclass

from skillscope.retrieval.bm25 import BM25Index, BM25Result
from skillscope.retrieval.config import DenseHybridConfig
from skillscope.retrieval.corpus import CorpusDocument
from skillscope.retrieval.dense import DenseResult, DenseRetriever
from skillscope.retrieval.filters import RetrievalFilters


@dataclass(frozen=True, slots=True)
class HybridResult:
    """One fused result with both source ranks and source scores."""

    document: CorpusDocument
    fused_score: float
    bm25_rank: int | None
    dense_rank: int | None
    bm25_score: float | None
    dense_similarity: float | None


class HybridRetriever:
    """Retrieve equal-depth candidates and fuse their one-based ranks."""

    def __init__(
        self,
        bm25: BM25Index,
        dense: DenseRetriever,
        config: DenseHybridConfig,
    ) -> None:
        if bm25.snapshot_sha256 != dense.corpus.snapshot_sha256:
            raise ValueError("BM25 and dense retrievers use different corpus snapshots")
        if bm25.snapshot_sha256 != config.corpus_snapshot_sha256:
            raise ValueError("hybrid configuration uses a different corpus snapshot")
        self.bm25 = bm25
        self.dense = dense
        self.config = config

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        filters: RetrievalFilters | None = None,
    ) -> tuple[HybridResult, ...]:
        """Apply filters before both candidate rankings, then fuse by RRF."""

        result_limit = top_k if top_k is not None else self.config.default_top_k
        if not 1 <= result_limit <= self.config.rrf_candidate_depth:
            raise ValueError(f"top_k must be between 1 and {self.config.rrf_candidate_depth}")
        bm25_results = self.bm25.search(
            query,
            top_k=self.config.rrf_candidate_depth,
            filters=filters,
        )
        dense_results = self.dense.search(
            query,
            top_k=self.config.rrf_candidate_depth,
            filters=filters,
        )
        return reciprocal_rank_fusion(
            bm25_results,
            dense_results,
            rrf_k=self.config.rrf_k,
            bm25_weight=self.config.bm25_weight,
            dense_weight=self.config.dense_weight,
            top_k=result_limit,
        )


def reciprocal_rank_fusion(
    bm25_results: tuple[BM25Result, ...],
    dense_results: tuple[DenseResult, ...],
    *,
    rrf_k: int,
    bm25_weight: float,
    dense_weight: float,
    top_k: int,
) -> tuple[HybridResult, ...]:
    """Fuse independent ranks without adding incomparable raw scores."""

    if not 1 <= rrf_k <= 10_000:
        raise ValueError("rrf_k must be between 1 and 10000")
    if bm25_weight <= 0.0 or dense_weight <= 0.0:
        raise ValueError("RRF weights must be positive")
    if not 1 <= top_k <= 100:
        raise ValueError("top_k must be between 1 and 100")

    bm25_by_id = _unique_bm25_results(bm25_results)
    dense_by_id = _unique_dense_results(dense_results)
    document_ids = set(bm25_by_id) | set(dense_by_id)
    fused: list[HybridResult] = []
    for document_id in document_ids:
        bm25_item = bm25_by_id.get(document_id)
        dense_item = dense_by_id.get(document_id)
        if bm25_item is not None and dense_item is not None:
            if bm25_item[1].document.skill_id != dense_item[1].document.skill_id:
                raise ValueError("retrievers disagree about a stable document identity")
        if bm25_item is not None:
            document = bm25_item[1].document
        elif dense_item is not None:
            document = dense_item[1].document
        else:
            raise AssertionError("fused document must occur in at least one source ranking")
        bm25_rank = None if bm25_item is None else bm25_item[0]
        dense_rank = None if dense_item is None else dense_item[0]
        score = 0.0
        if bm25_rank is not None:
            score += bm25_weight / (rrf_k + bm25_rank)
        if dense_rank is not None:
            score += dense_weight / (rrf_k + dense_rank)
        fused.append(
            HybridResult(
                document=document,
                fused_score=score,
                bm25_rank=bm25_rank,
                dense_rank=dense_rank,
                bm25_score=None if bm25_item is None else bm25_item[1].score,
                dense_similarity=(None if dense_item is None else dense_item[1].cosine_similarity),
            )
        )

    fused.sort(
        key=lambda result: (
            -result.fused_score,
            min(rank for rank in (result.bm25_rank, result.dense_rank) if rank is not None),
            result.document.repository_full_name.casefold(),
            result.document.path.casefold(),
            result.document.document_id,
        )
    )
    return tuple(fused[:top_k])


def _unique_bm25_results(
    results: tuple[BM25Result, ...],
) -> dict[str, tuple[int, BM25Result]]:
    indexed = {
        result.document.document_id: (rank, result) for rank, result in enumerate(results, start=1)
    }
    if len(indexed) != len(results):
        raise ValueError("BM25 ranking contains duplicate documents")
    return indexed


def _unique_dense_results(
    results: tuple[DenseResult, ...],
) -> dict[str, tuple[int, DenseResult]]:
    indexed = {
        result.document.document_id: (rank, result) for rank, result in enumerate(results, start=1)
    }
    if len(indexed) != len(results):
        raise ValueError("dense ranking contains duplicate documents")
    return indexed
