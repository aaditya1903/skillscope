"""Same-snapshot method comparison, latency, report, and test-lock coverage."""

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest

from skillscope.db.enums import EvaluationSplit, RetrievalMethod, ValidationStatus
from skillscope.evaluation.comparison import (
    EvaluationHit,
    RetrievalComparisonReport,
    evaluate_retrieval_methods,
    serialize_comparison_report,
    write_comparison_report,
)
from skillscope.evaluation.data import (
    EvaluationQueryRecord,
    QrelRecord,
    build_qrel_set,
    build_query_set,
    serialize_query_set,
    sha256_bytes,
)
from skillscope.evaluation.runner import TestSplitLockedError
from skillscope.retrieval.config import DenseHybridConfig
from skillscope.retrieval.corpus import CorpusDocument, LexicalFields

SNAPSHOT_SHA = "a" * 64
ALPHA_ID = "github:101:skills/alpha/SKILL.md"
BETA_ID = "github:102:skills/beta/SKILL.md"


def _document(document_id: str, number: int, name: str) -> CorpusDocument:
    return CorpusDocument(
        document_id=document_id,
        skill_id=UUID(int=number),
        repository_id=100 + number,
        repository_full_name=f"example/{name}",
        path=document_id.split(":", maxsplit=2)[2],
        name=name,
        safe_snippet="Body-free synthetic result.",
        validation_status=ValidationStatus.VALID,
        content_sha256=f"{number}" * 64,
        fields=LexicalFields(name, name, "", "", ""),
        tokens=(name,),
    )


ALPHA = _document(ALPHA_ID, 1, "alpha")
BETA = _document(BETA_ID, 2, "beta")


@dataclass
class FakeRetriever:
    method: RetrievalMethod
    results: tuple[EvaluationHit, ...]
    snapshot_sha256: str = SNAPSHOT_SHA
    calls: int = 0

    def search(self, query: str, *, top_k: int) -> tuple[EvaluationHit, ...]:
        self.calls += 1
        return self.results[:top_k]


def _retrievers() -> tuple[FakeRetriever, FakeRetriever, FakeRetriever]:
    return (
        FakeRetriever(
            RetrievalMethod.BM25,
            (
                EvaluationHit(ALPHA, 2.0, "bm25", bm25_rank=1, bm25_score=2.0),
                EvaluationHit(BETA, 1.0, "bm25", bm25_rank=2, bm25_score=1.0),
            ),
        ),
        FakeRetriever(
            RetrievalMethod.DENSE,
            (
                EvaluationHit(
                    BETA,
                    0.9,
                    "cosine_similarity",
                    dense_rank=1,
                    dense_similarity=0.9,
                ),
                EvaluationHit(
                    ALPHA,
                    0.8,
                    "cosine_similarity",
                    dense_rank=2,
                    dense_similarity=0.8,
                ),
            ),
        ),
        FakeRetriever(
            RetrievalMethod.HYBRID,
            (
                EvaluationHit(
                    ALPHA,
                    0.03,
                    "rrf",
                    bm25_rank=1,
                    dense_rank=2,
                    bm25_score=2.0,
                    dense_similarity=0.8,
                ),
                EvaluationHit(
                    BETA,
                    0.03,
                    "rrf",
                    bm25_rank=2,
                    dense_rank=1,
                    bm25_score=1.0,
                    dense_similarity=0.9,
                ),
            ),
        ),
    )


def _query_set():
    queries = tuple(
        EvaluationQueryRecord(
            query_id=f"q{number:03d}",
            query_text=f"find alpha workflow {number}",
            category="synthetic_category",
            split=(EvaluationSplit.DEVELOPMENT if number <= 15 else EvaluationSplit.TEST),
            intent=f"Find the alpha workflow for synthetic comparison query {number}.",
            pool_seed_document_ids=(ALPHA_ID,),
        )
        for number in range(1, 21)
    )
    return build_query_set(
        name="comparison-queries",
        corpus_snapshot_path="data/manifests/test.jsonl",
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        queries=queries,
    )


def _qrels(query_set):
    judgements = tuple(
        judgement
        for query in query_set.queries
        for judgement in (
            QrelRecord(
                query_id=query.query_id,
                document_id=ALPHA_ID,
                content_sha256="1" * 64,
                relevance=2,
                rationale="Alpha directly satisfies the synthetic query.",
            ),
            QrelRecord(
                query_id=query.query_id,
                document_id=BETA_ID,
                content_sha256="2" * 64,
                relevance=0,
            ),
        )
    )
    return build_qrel_set(
        name="comparison-qrels",
        query_set_path="data/evaluation/queries.jsonl",
        query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
        candidate_pool_path="data/evaluation/pool.jsonl",
        candidate_pool_sha256="c" * 64,
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        judgements=judgements,
    )


def _config() -> DenseHybridConfig:
    return DenseHybridConfig(
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="d" * 40,
        sentence_transformers_version="6.0.0",
        batch_size=16,
        default_top_k=10,
        bm25_weight=1.0,
        dense_weight=1.0,
        corpus_snapshot_path="data/manifests/test.jsonl",
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        bm25_config_path="config/retrieval/bm25.json",
        bm25_config_sha256="e" * 64,
        eligible_validation_statuses=("valid", "warning"),
    )


def _evaluate(
    *,
    split: EvaluationSplit = EvaluationSplit.DEVELOPMENT,
    allow_test: bool = False,
) -> tuple[RetrievalComparisonReport, tuple[FakeRetriever, FakeRetriever, FakeRetriever]]:
    query_set = _query_set()
    retrievers = _retrievers()
    report = evaluate_retrieval_methods(
        retrievers,
        query_set,
        _qrels(query_set),
        _config(),
        split=split,
        generated_at=datetime(2030, 1, 1, tzinfo=UTC),
        git_commit="f" * 40,
        query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
        qrels_sha256="1" * 64,
        evaluation_config_sha256="2" * 64,
        bm25_config_sha256="3" * 64,
        dense_hybrid_config_sha256="4" * 64,
        allow_test=allow_test,
    )
    return report, retrievers


def test_comparison_uses_same_queries_qrels_and_records_latency() -> None:
    report, retrievers = _evaluate()

    assert [method.method for method in report.methods] == [
        RetrievalMethod.BM25,
        RetrievalMethod.DENSE,
        RetrievalMethod.HYBRID,
    ]
    assert report.methods[0].ndcg_at_10 == pytest.approx(1.0)
    assert report.methods[1].mrr_at_10 == pytest.approx(0.5)
    assert report.methods[2].recall_at_10 == pytest.approx(1.0)
    assert all(method.query_count == 15 for method in report.methods)
    assert all(method.latency.sample_count == 15 for method in report.methods)
    assert all(method.latency.p95_ms >= method.latency.p50_ms for method in report.methods)
    assert all(retriever.calls == 16 for retriever in retrievers)


def test_comparison_test_split_requires_explicit_unlock() -> None:
    query_set = _query_set()

    with pytest.raises(TestSplitLockedError, match="locked"):
        evaluate_retrieval_methods(
            _retrievers(),
            query_set,
            _qrels(query_set),
            _config(),
            split=EvaluationSplit.TEST,
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="f" * 40,
            query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
            qrels_sha256="1" * 64,
            evaluation_config_sha256="2" * 64,
            bm25_config_sha256="3" * 64,
            dense_hybrid_config_sha256="4" * 64,
        )


def test_unlocked_test_comparison_evaluates_only_held_out_queries() -> None:
    report, retrievers = _evaluate(split=EvaluationSplit.TEST, allow_test=True)

    assert all(method.query_count == 5 for method in report.methods)
    assert all(retriever.calls == 6 for retriever in retrievers)
    assert all(query.query_id >= "q016" for method in report.methods for query in method.queries)


def test_comparison_rejects_snapshot_mismatch() -> None:
    query_set = _query_set()
    retrievers = _retrievers()
    retrievers[1].snapshot_sha256 = "b" * 64

    with pytest.raises(ValueError, match="frozen corpus snapshot"):
        evaluate_retrieval_methods(
            retrievers,
            query_set,
            _qrels(query_set),
            _config(),
            split=EvaluationSplit.DEVELOPMENT,
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="f" * 40,
            query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
            qrels_sha256="1" * 64,
            evaluation_config_sha256="2" * 64,
            bm25_config_sha256="3" * 64,
            dense_hybrid_config_sha256="4" * 64,
        )


def test_report_is_canonical_body_free_and_test_output_is_single_use(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    report, _ = _evaluate(split=EvaluationSplit.TEST, allow_test=True)
    serialized = serialize_comparison_report(report)
    monkeypatch.chdir(tmp_path)
    path = Path("comparison.json")

    write_comparison_report(path, report, refuse_overwrite=True)

    assert path.read_bytes() == serialized
    assert serialized.endswith(b"\n")
    assert b"body_text" not in serialized
    assert b"Body-free synthetic result" not in serialized
    with pytest.raises(ValueError, match="already exists"):
        write_comparison_report(path, report, refuse_overwrite=True)
