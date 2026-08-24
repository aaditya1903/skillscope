"""Frozen BM25 evaluation report and test-lock tests."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from skillscope.db.enums import EvaluationSplit, ValidationStatus
from skillscope.evaluation.data import (
    EvaluationQueryRecord,
    QrelRecord,
    build_qrel_set,
    build_query_set,
    serialize_query_set,
    sha256_bytes,
)
from skillscope.evaluation.runner import (
    TestSplitLockedError,
    evaluate_bm25,
    serialize_evaluation_report,
)
from skillscope.retrieval.bm25 import BM25Index
from skillscope.retrieval.config import BM25BaselineConfig
from skillscope.retrieval.corpus import CorpusDocument, FrozenCorpus, LexicalFields

SNAPSHOT_SHA = "a" * 64
ALPHA_ID = "github:101:skills/alpha/SKILL.md"
BETA_ID = "github:102:skills/beta/SKILL.md"


def _document(document_id: str, number: int, token: str) -> CorpusDocument:
    fields = LexicalFields(token, token, "", "", "")
    return CorpusDocument(
        document_id=document_id,
        skill_id=UUID(int=number),
        repository_id=100 + number,
        repository_full_name=f"example/{token}",
        path=document_id.split(":", maxsplit=2)[2],
        name=token,
        safe_snippet=f"Synthetic {token} result.",
        validation_status=ValidationStatus.VALID,
        content_sha256=f"{number:x}" * 64,
        fields=fields,
        tokens=(token, token),
    )


def _index() -> BM25Index:
    corpus = FrozenCorpus(
        snapshot_path="data/manifests/test.jsonl",
        snapshot_sha256=SNAPSHOT_SHA,
        documents=(
            _document(ALPHA_ID, 1, "alpha"),
            _document(BETA_ID, 2, "beta"),
        ),
    )
    config = BM25BaselineConfig(
        k1=1.5,
        b=0.75,
        default_top_k=10,
        corpus_snapshot_path=corpus.snapshot_path,
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        eligible_validation_statuses=("valid", "warning"),
    )
    return BM25Index(corpus, config)


def _query_set():
    queries = tuple(
        EvaluationQueryRecord(
            query_id=f"q{number:03d}",
            query_text=("beta workflow" if number == 1 else f"alpha workflow {number}"),
            category="synthetic_category",
            split=(EvaluationSplit.DEVELOPMENT if number <= 15 else EvaluationSplit.TEST),
            intent=f"Find the correct synthetic workflow for evaluation query {number}.",
            pool_seed_document_ids=(ALPHA_ID,),
        )
        for number in range(1, 21)
    )
    return build_query_set(
        name="synthetic-query-set",
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
                rationale="Alpha directly satisfies the synthetic information need.",
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
        name="synthetic-qrels",
        query_set_path="data/evaluation/queries.jsonl",
        query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
        candidate_pool_path="data/evaluation/pool.jsonl",
        candidate_pool_sha256="c" * 64,
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        judgements=judgements,
    )


def test_development_evaluation_records_metrics_and_failures() -> None:
    query_set = _query_set()
    report = evaluate_bm25(
        _index(),
        query_set,
        _qrels(query_set),
        split=EvaluationSplit.DEVELOPMENT,
        generated_at=datetime(2030, 1, 1, tzinfo=UTC),
        git_commit="d" * 40,
        query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
        qrels_sha256="e" * 64,
        bm25_config_sha256="f" * 64,
    )

    assert report.query_count == 15
    assert 0.0 < report.ndcg_at_10 < 1.0
    assert 0.0 < report.mrr_at_10 < 1.0
    assert 0.0 < report.recall_at_10 < 1.0
    assert report.failure_examples[0].query_id == "q001"
    assert report.failure_examples[0].failure_type == "no_relevant_result_in_top_10"
    assert all(query.query_id <= "q015" for query in report.queries)


def test_test_split_is_locked_by_default() -> None:
    query_set = _query_set()

    with pytest.raises(TestSplitLockedError, match="locked until"):
        evaluate_bm25(
            _index(),
            query_set,
            _qrels(query_set),
            split=EvaluationSplit.TEST,
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="d" * 40,
            query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
            qrels_sha256="e" * 64,
            bm25_config_sha256="f" * 64,
        )


def test_explicit_test_unlock_evaluates_only_test_queries() -> None:
    query_set = _query_set()
    report = evaluate_bm25(
        _index(),
        query_set,
        _qrels(query_set),
        split=EvaluationSplit.TEST,
        generated_at=datetime(2030, 1, 1, tzinfo=UTC),
        git_commit="d" * 40,
        query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
        qrels_sha256="e" * 64,
        bm25_config_sha256="f" * 64,
        allow_test=True,
    )

    assert report.query_count == 5
    assert report.ndcg_at_10 == pytest.approx(1.0)
    assert all(query.query_id >= "q016" for query in report.queries)


def test_report_serialization_is_canonical_and_body_free() -> None:
    query_set = _query_set()
    report = evaluate_bm25(
        _index(),
        query_set,
        _qrels(query_set),
        split=EvaluationSplit.DEVELOPMENT,
        generated_at=datetime(2030, 1, 1, tzinfo=UTC),
        git_commit="d" * 40,
        query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
        qrels_sha256="e" * 64,
        bm25_config_sha256="f" * 64,
    )

    serialized = serialize_evaluation_report(report)

    assert serialized.endswith(b"\n")
    assert b"body_text" not in serialized
    assert b"Synthetic alpha result" not in serialized
    assert serialized == serialize_evaluation_report(report)
