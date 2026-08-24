"""Candidate-pool and rank-blinded worksheet tests."""

import csv
from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from skillscope.db.enums import EvaluationSplit, ValidationStatus
from skillscope.evaluation.data import (
    EvaluationDataError,
    EvaluationQueryRecord,
    QuerySet,
    build_query_set,
    serialize_query_set,
    sha256_bytes,
)
from skillscope.evaluation.pooling import (
    WORKSHEET_COLUMNS,
    build_bm25_candidate_pool,
    qrels_from_label_worksheet,
    read_candidate_pool,
    serialize_candidate_pool,
    serialize_label_worksheet,
    write_candidate_pool,
    write_label_worksheet,
)
from skillscope.retrieval.bm25 import BM25Index
from skillscope.retrieval.config import BM25BaselineConfig
from skillscope.retrieval.corpus import CorpusDocument, FrozenCorpus, LexicalFields

SNAPSHOT_SHA = "a" * 64
ALPHA_ID = "github:101:skills/alpha/SKILL.md"
BETA_ID = "github:102:skills/beta/SKILL.md"


def _document(document_id: str, number: int, token: str) -> CorpusDocument:
    repository_id = int(document_id.split(":", maxsplit=2)[1])
    path = document_id.split(":", maxsplit=2)[2]
    fields = LexicalFields(
        name_text=token,
        description_text=f"{token} synthetic retrieval tool",
        metadata_text="",
        heading_text="",
        body_text="",
    )
    return CorpusDocument(
        document_id=document_id,
        skill_id=UUID(int=number),
        repository_id=repository_id,
        repository_full_name=f"example/{token}",
        path=path,
        name=token,
        safe_snippet=f"Synthetic {token} candidate.",
        validation_status=ValidationStatus.VALID,
        content_sha256=f"{number:x}" * 64,
        fields=fields,
        tokens=tuple(fields.combined_text.split()),
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


def _query_set() -> QuerySet:
    queries = tuple(
        EvaluationQueryRecord(
            query_id=f"q{number:03d}",
            query_text=f"alpha workflow number {number}",
            category="synthetic_category",
            split=(EvaluationSplit.DEVELOPMENT if number <= 15 else EvaluationSplit.TEST),
            intent=f"Find the alpha or beta workflow for synthetic task number {number}.",
            pool_seed_document_ids=(BETA_ID,),
        )
        for number in range(1, 21)
    )
    return build_query_set(
        name="synthetic-queries",
        corpus_snapshot_path="data/manifests/test.jsonl",
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        queries=queries,
    )


def _pool():
    query_set = _query_set()
    query_sha = sha256_bytes(serialize_query_set(query_set))
    return build_bm25_candidate_pool(
        _index(),
        query_set,
        query_set_path="data/evaluation/queries.jsonl",
        query_set_sha256=query_sha,
        pool_depth=10,
    )


def _complete_worksheet(path: Path) -> None:
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        fieldnames = tuple(reader.fieldnames or ())
        rows = list(reader)
    assert fieldnames == WORKSHEET_COLUMNS
    for row in rows:
        if row["document_id"] == BETA_ID:
            row["relevance"] = "2"
            row["rationale"] = "The seeded beta skill directly satisfies this synthetic task."
        else:
            row["relevance"] = "0"
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def test_pool_unions_bm25_results_and_query_seeds() -> None:
    pool = _pool()
    first = [item for item in pool.items if item.query_id == "q001"]

    assert len(first) == 2
    assert first[0].document_id == ALPHA_ID
    assert first[0].sources == ("bm25",)
    assert first[0].bm25_rank == 1
    assert first[1].document_id == BETA_ID
    assert first[1].sources == ("query_seed",)
    assert first[1].bm25_rank is None


def test_pool_round_trip_is_canonical(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    pool = _pool()
    path = Path("pool.jsonl")

    write_candidate_pool(path, pool)

    assert read_candidate_pool(path) == pool
    assert path.read_bytes() == serialize_candidate_pool(pool)


def test_worksheet_is_deterministic_and_hides_ranks_and_sources() -> None:
    pool = _pool()
    query_set = _query_set()
    pool_sha = sha256_bytes(serialize_candidate_pool(pool))

    first = serialize_label_worksheet(pool, query_set, candidate_pool_sha256=pool_sha)
    second = serialize_label_worksheet(pool, query_set, candidate_pool_sha256=pool_sha)

    assert first == second
    header = first.splitlines()[0].decode()
    assert "bm25_rank" not in header
    assert "sources" not in header
    assert "split" not in header
    assert "query_intent" in header
    assert first.endswith(b"\n")


@pytest.mark.parametrize(
    "dangerous_name",
    ['=HYPERLINK("https://example.invalid")', "  +SUM(1,1)", "\t@unsafe"],
)
def test_worksheet_neutralizes_spreadsheet_formula_metadata(dangerous_name: str) -> None:
    pool = _pool()
    dangerous = pool.items[0].model_copy(update={"name": dangerous_name})
    changed = replace(pool, items=(dangerous, *pool.items[1:]))
    pool_sha = sha256_bytes(serialize_candidate_pool(changed))

    worksheet = serialize_label_worksheet(
        changed,
        _query_set(),
        candidate_pool_sha256=pool_sha,
    )

    rows = list(csv.DictReader(worksheet.decode().splitlines()))
    assert any(row["name"] == f"'{dangerous_name}" for row in rows)


def test_completed_worksheet_builds_sorted_qrels(tmp_path: Path) -> None:
    pool = _pool()
    query_set = _query_set()
    pool_sha = sha256_bytes(serialize_candidate_pool(pool))
    path = tmp_path / "labels.csv"
    write_label_worksheet(path, pool, query_set, candidate_pool_sha256=pool_sha)
    _complete_worksheet(path)

    qrels = qrels_from_label_worksheet(
        path,
        pool,
        query_set,
        query_set_path="data/evaluation/queries.jsonl",
        candidate_pool_path="data/evaluation/pool.jsonl",
        candidate_pool_sha256=pool_sha,
    )

    assert qrels.header.query_count == 20
    assert qrels.header.judgement_count == 40
    assert qrels.header.relevant_judgement_count == 20
    assert qrels.judgements[0].query_id == "q001"
    assert qrels.judgements[-1].query_id == "q020"


def test_unfinished_worksheet_is_rejected(tmp_path: Path) -> None:
    pool = _pool()
    query_set = _query_set()
    pool_sha = sha256_bytes(serialize_candidate_pool(pool))
    path = tmp_path / "labels.csv"
    write_label_worksheet(path, pool, query_set, candidate_pool_sha256=pool_sha)

    with pytest.raises(EvaluationDataError, match="every worksheet row"):
        qrels_from_label_worksheet(
            path,
            pool,
            query_set,
            query_set_path="data/evaluation/queries.jsonl",
            candidate_pool_path="data/evaluation/pool.jsonl",
            candidate_pool_sha256=pool_sha,
        )


def test_modified_evidence_column_is_rejected(tmp_path: Path) -> None:
    pool = _pool()
    query_set = _query_set()
    pool_sha = sha256_bytes(serialize_candidate_pool(pool))
    path = tmp_path / "labels.csv"
    write_label_worksheet(path, pool, query_set, candidate_pool_sha256=pool_sha)
    _complete_worksheet(path)
    content = path.read_text()
    path.write_text(content.replace("Synthetic alpha candidate.", "tampered", 1))

    with pytest.raises(EvaluationDataError, match="modified evidence"):
        qrels_from_label_worksheet(
            path,
            pool,
            query_set,
            query_set_path="data/evaluation/queries.jsonl",
            candidate_pool_path="data/evaluation/pool.jsonl",
            candidate_pool_sha256=pool_sha,
        )


def test_extra_worksheet_values_are_rejected(tmp_path: Path) -> None:
    pool = _pool()
    query_set = _query_set()
    pool_sha = sha256_bytes(serialize_candidate_pool(pool))
    path = tmp_path / "labels.csv"
    write_label_worksheet(path, pool, query_set, candidate_pool_sha256=pool_sha)
    lines = path.read_text().splitlines()
    lines[1] += ",unexpected"
    path.write_text("\n".join(lines) + "\n")

    with pytest.raises(EvaluationDataError, match="unexpected columns or values"):
        qrels_from_label_worksheet(
            path,
            pool,
            query_set,
            query_set_path="data/evaluation/queries.jsonl",
            candidate_pool_path="data/evaluation/pool.jsonl",
            candidate_pool_sha256=pool_sha,
        )


def test_positive_label_requires_rationale(tmp_path: Path) -> None:
    pool = _pool()
    query_set = _query_set()
    pool_sha = sha256_bytes(serialize_candidate_pool(pool))
    path = tmp_path / "labels.csv"
    write_label_worksheet(path, pool, query_set, candidate_pool_sha256=pool_sha)
    with path.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source)
        rows = list(reader)
    rows[0]["relevance"] = "2"
    with path.open("w", newline="", encoding="utf-8") as destination:
        writer = csv.DictWriter(destination, fieldnames=WORKSHEET_COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    with pytest.raises(EvaluationDataError, match="require a rationale"):
        qrels_from_label_worksheet(
            path,
            pool,
            query_set,
            query_set_path="data/evaluation/queries.jsonl",
            candidate_pool_path="data/evaluation/pool.jsonl",
            candidate_pool_sha256=pool_sha,
        )
