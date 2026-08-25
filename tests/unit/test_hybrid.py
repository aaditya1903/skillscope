"""Exact reciprocal-rank-fusion and shared-filter tests."""

from uuid import UUID

import pytest

from skillscope.db.enums import LicenseStatus, ValidationStatus
from skillscope.retrieval.bm25 import BM25Index, BM25Result
from skillscope.retrieval.config import BM25BaselineConfig, DenseHybridConfig
from skillscope.retrieval.corpus import CorpusDocument, FrozenCorpus, LexicalFields
from skillscope.retrieval.dense import DenseResult
from skillscope.retrieval.filters import RetrievalFilters
from skillscope.retrieval.hybrid import HybridRetriever, reciprocal_rank_fusion


def _document(
    number: int,
    *,
    repository: str,
    license_status: LicenseStatus = LicenseStatus.PERMISSIVE,
    validation_status: ValidationStatus = ValidationStatus.VALID,
    has_scripts: bool = False,
) -> CorpusDocument:
    path = f"skills/{number}/SKILL.md"
    return CorpusDocument(
        document_id=f"github:{number}:{path}",
        skill_id=UUID(int=number),
        repository_id=number,
        repository_full_name=repository,
        path=path,
        name=f"skill-{number}",
        safe_snippet="Synthetic.",
        validation_status=validation_status,
        content_sha256=f"{number}" * 64,
        fields=LexicalFields(f"skill {number}", "", "", "", ""),
        tokens=("skill", str(number)),
        license_status=license_status,
        has_scripts=has_scripts,
    )


def _bm25(document: CorpusDocument, score: float) -> BM25Result:
    return BM25Result(document=document, score=score, matched_terms=(), term_scores=())


def _dense(document: CorpusDocument, similarity: float) -> DenseResult:
    return DenseResult(
        document=document,
        cosine_distance=1.0 - similarity,
        cosine_similarity=similarity,
    )


def test_rrf_fuses_overlapping_and_non_overlapping_rankings_exactly() -> None:
    alpha = _document(1, repository="example/alpha")
    beta = _document(2, repository="example/beta")
    gamma = _document(3, repository="example/gamma")

    results = reciprocal_rank_fusion(
        (_bm25(alpha, 10.0), _bm25(beta, 5.0)),
        (_dense(beta, 0.9), _dense(gamma, 0.8)),
        rrf_k=60,
        bm25_weight=1.0,
        dense_weight=1.0,
        top_k=3,
    )

    assert [result.document for result in results] == [beta, alpha, gamma]
    assert results[0].fused_score == pytest.approx(1 / 62 + 1 / 61)
    assert (results[0].bm25_rank, results[0].dense_rank) == (2, 1)
    assert (results[1].bm25_rank, results[1].dense_rank) == (1, None)
    assert (results[2].bm25_rank, results[2].dense_rank) == (None, 2)


def test_rrf_applies_weights_to_ranks_not_raw_scores() -> None:
    alpha = _document(1, repository="example/alpha")
    beta = _document(2, repository="example/beta")

    results = reciprocal_rank_fusion(
        (_bm25(alpha, 0.001),),
        (_dense(beta, 0.999),),
        rrf_k=60,
        bm25_weight=2.0,
        dense_weight=1.0,
        top_k=2,
    )

    assert [result.document for result in results] == [alpha, beta]
    assert results[0].fused_score == pytest.approx(2 / 61)
    assert results[1].fused_score == pytest.approx(1 / 61)


def test_rrf_ties_use_stable_repository_path_order() -> None:
    zeta = _document(1, repository="zeta/repository")
    alpha = _document(2, repository="alpha/repository")

    results = reciprocal_rank_fusion(
        (_bm25(zeta, 10.0),),
        (_dense(alpha, 0.1),),
        rrf_k=60,
        bm25_weight=1.0,
        dense_weight=1.0,
        top_k=2,
    )

    assert [result.document for result in results] == [alpha, zeta]


def test_rrf_rejects_duplicate_documents_and_invalid_parameters() -> None:
    alpha = _document(1, repository="example/alpha")

    with pytest.raises(ValueError, match="duplicate"):
        reciprocal_rank_fusion(
            (_bm25(alpha, 2.0), _bm25(alpha, 1.0)),
            (),
            rrf_k=60,
            bm25_weight=1.0,
            dense_weight=1.0,
            top_k=2,
        )
    with pytest.raises(ValueError, match="positive"):
        reciprocal_rank_fusion(
            (_bm25(alpha, 1.0),),
            (),
            rrf_k=60,
            bm25_weight=0.0,
            dense_weight=1.0,
            top_k=1,
        )


def test_shared_filters_require_every_selected_attribute() -> None:
    allowed = _document(
        1,
        repository="example/allowed",
        has_scripts=True,
    )
    missing_scripts = _document(2, repository="example/no-scripts")
    restrictive = _document(
        3,
        repository="example/restrictive",
        license_status=LicenseStatus.RESTRICTIVE,
        has_scripts=True,
    )
    invalid = _document(
        4,
        repository="example/invalid",
        validation_status=ValidationStatus.INVALID,
        has_scripts=True,
    )
    corpus = FrozenCorpus(
        "snapshot.jsonl", "a" * 64, (allowed, missing_scripts, restrictive, invalid)
    )
    filters = RetrievalFilters(
        license_statuses=frozenset({LicenseStatus.PERMISSIVE}),
        validation_statuses=frozenset({ValidationStatus.VALID}),
        has_scripts=True,
    )

    assert filters.document_ids(corpus) == frozenset({allowed.document_id})


def test_hybrid_retriever_uses_top_50_and_passes_filters_to_both_rankers() -> None:
    alpha = _document(1, repository="example/alpha", has_scripts=True)
    beta = _document(2, repository="example/beta")
    corpus = FrozenCorpus("data/manifests/test.jsonl", "a" * 64, (alpha, beta))
    baseline = BM25BaselineConfig(
        k1=1.5,
        b=0.75,
        default_top_k=10,
        corpus_snapshot_path=corpus.snapshot_path,
        corpus_snapshot_sha256=corpus.snapshot_sha256,
        eligible_validation_statuses=("valid", "warning"),
    )
    config = DenseHybridConfig(
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="1" * 40,
        sentence_transformers_version="6.0.0",
        batch_size=16,
        default_top_k=10,
        bm25_weight=1.0,
        dense_weight=1.0,
        corpus_snapshot_path=corpus.snapshot_path,
        corpus_snapshot_sha256=corpus.snapshot_sha256,
        bm25_config_path="config/retrieval/bm25.json",
        bm25_config_sha256="b" * 64,
        eligible_validation_statuses=("valid", "warning"),
    )
    filters = RetrievalFilters(has_scripts=True)

    class FakeDense:
        def __init__(self) -> None:
            self.corpus = corpus
            self.received: tuple[int, RetrievalFilters | None] | None = None

        def search(
            self,
            query: str,
            *,
            top_k: int,
            filters: RetrievalFilters | None = None,
        ) -> tuple[DenseResult, ...]:
            self.received = (top_k, filters)
            return (_dense(alpha, 1.0),)

    dense = FakeDense()
    retriever = HybridRetriever(BM25Index(corpus, baseline), dense, config)  # type: ignore[arg-type]

    results = retriever.search("skill", filters=filters)

    assert dense.received == (50, filters)
    assert [result.document for result in results] == [alpha]
    assert results[0].bm25_rank == results[0].dense_rank == 1
