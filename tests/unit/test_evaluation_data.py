"""Canonical query and qrel dataset validation tests."""

from dataclasses import replace
from pathlib import Path

import pytest

from skillscope.db.enums import EvaluationSplit
from skillscope.evaluation.data import (
    EvaluationDataError,
    EvaluationQueryRecord,
    QrelRecord,
    QrelSet,
    QuerySet,
    build_qrel_set,
    build_query_set,
    read_qrel_set,
    read_query_set,
    serialize_qrel_set,
    serialize_query_set,
    sha256_bytes,
    validate_evaluation_dataset,
    write_qrel_set,
    write_query_set,
)

SNAPSHOT_SHA = "a" * 64
QUERY_SET_PATH = "data/evaluation/test-queries.jsonl"
POOL_PATH = "data/evaluation/test-pool.jsonl"
DOCUMENT_ID = "github:123:skills/example/SKILL.md"
CONTENT_SHA = "b" * 64


def _query_set() -> QuerySet:
    queries = tuple(
        EvaluationQueryRecord(
            query_id=f"q{number:03d}",
            query_text=f"realistic retrieval task number {number}",
            category="synthetic_category",
            split=(EvaluationSplit.DEVELOPMENT if number <= 15 else EvaluationSplit.TEST),
            intent=f"Find the correct synthetic skill for retrieval task number {number}.",
            pool_seed_document_ids=(DOCUMENT_ID,),
        )
        for number in range(1, 21)
    )
    return build_query_set(
        name="test-queries",
        corpus_snapshot_path="data/manifests/test.jsonl",
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        queries=queries,
    )


def _qrels(query_set: QuerySet) -> QrelSet:
    query_sha = sha256_bytes(serialize_query_set(query_set))
    judgements = tuple(
        QrelRecord(
            query_id=query.query_id,
            document_id=DOCUMENT_ID,
            content_sha256=CONTENT_SHA,
            relevance=2,
            rationale="Directly satisfies the synthetic information need.",
        )
        for query in query_set.queries
    )
    return build_qrel_set(
        name="test-qrels",
        query_set_path=QUERY_SET_PATH,
        query_set_sha256=query_sha,
        candidate_pool_path=POOL_PATH,
        candidate_pool_sha256="c" * 64,
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        judgements=judgements,
    )


def test_query_set_round_trip_is_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    query_set = _query_set()
    path = Path("queries.jsonl")

    write_query_set(path, query_set)

    assert read_query_set(path) == query_set
    assert path.read_bytes() == serialize_query_set(query_set)
    assert path.read_bytes().endswith(b"\n")


def test_query_set_reader_rejects_noncanonical_jsonl(tmp_path: Path) -> None:
    path = tmp_path / "queries.jsonl"
    path.write_bytes(serialize_query_set(_query_set()).replace(b":", b": ", 1))

    with pytest.raises(EvaluationDataError, match="not canonical"):
        read_query_set(path)


def test_query_set_rejects_duplicate_or_unsorted_ids() -> None:
    query_set = _query_set()
    changed = replace(query_set, queries=tuple(reversed(query_set.queries)))

    with pytest.raises(EvaluationDataError, match="ascending query IDs"):
        serialize_query_set(changed)


def test_query_set_rejects_too_few_queries() -> None:
    query_set = _query_set()

    with pytest.raises(EvaluationDataError, match="20 to 30"):
        build_query_set(
            name="too-small",
            corpus_snapshot_path=query_set.header.corpus_snapshot_path,
            corpus_snapshot_sha256=SNAPSHOT_SHA,
            queries=query_set.queries[:19],
        )


def test_query_record_rejects_path_traversal_seed() -> None:
    with pytest.raises(ValueError, match="safe path"):
        EvaluationQueryRecord(
            query_id="q001",
            query_text="find unsafe skill",
            category="security",
            split=EvaluationSplit.DEVELOPMENT,
            intent="Find a deliberately invalid traversal fixture for validation.",
            pool_seed_document_ids=("github:123:../SKILL.md",),
        )


def test_qrel_set_round_trip_is_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    qrels = _qrels(_query_set())
    path = Path("qrels.jsonl")

    write_qrel_set(path, qrels)

    assert read_qrel_set(path) == qrels
    assert path.read_bytes() == serialize_qrel_set(qrels)


def test_relevant_qrel_requires_a_rationale() -> None:
    query_set = _query_set()
    judgement = QrelRecord(
        query_id="q001",
        document_id=DOCUMENT_ID,
        content_sha256=CONTENT_SHA,
        relevance=2,
    )

    with pytest.raises(EvaluationDataError, match="require a rationale"):
        build_qrel_set(
            name="invalid",
            query_set_path=QUERY_SET_PATH,
            query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
            candidate_pool_path=POOL_PATH,
            candidate_pool_sha256="c" * 64,
            corpus_snapshot_sha256=SNAPSHOT_SHA,
            judgements=(judgement,),
        )


def test_dataset_validation_accepts_complete_current_references() -> None:
    query_set = _query_set()
    qrels = _qrels(query_set)

    validate_evaluation_dataset(
        query_set,
        qrels,
        query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
        available_documents={DOCUMENT_ID: CONTENT_SHA},
    )


def test_dataset_validation_rejects_a_missing_document_id() -> None:
    query_set = _query_set()

    with pytest.raises(EvaluationDataError, match="missing skill document ID"):
        validate_evaluation_dataset(
            query_set,
            _qrels(query_set),
            query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
            available_documents={},
        )


def test_dataset_validation_rejects_stale_document_content() -> None:
    query_set = _query_set()

    with pytest.raises(EvaluationDataError, match="content hash is stale"):
        validate_evaluation_dataset(
            query_set,
            _qrels(query_set),
            query_set_sha256=sha256_bytes(serialize_query_set(query_set)),
            available_documents={DOCUMENT_ID: "f" * 64},
        )


def test_dataset_validation_rejects_query_set_hash_drift() -> None:
    query_set = _query_set()

    with pytest.raises(EvaluationDataError, match="different query-set bytes"):
        validate_evaluation_dataset(
            query_set,
            _qrels(query_set),
            query_set_sha256="f" * 64,
            available_documents={DOCUMENT_ID: CONTENT_SHA},
        )
