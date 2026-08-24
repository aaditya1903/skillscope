"""Repository-level checks for the frozen Milestone 7 evaluation assets."""

from pathlib import Path

from skillscope.db.enums import EvaluationSplit, ValidationStatus
from skillscope.evaluation.config import load_evaluation_config
from skillscope.evaluation.data import read_query_set, serialize_query_set, sha256_bytes
from skillscope.ingestion.snapshot import read_dataset_snapshot

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = PROJECT_ROOT / "config/evaluation/evaluation-v1.json"


def test_shipped_query_set_matches_its_saved_hash_and_snapshot() -> None:
    config = load_evaluation_config(CONFIG_PATH)
    query_set = read_query_set(PROJECT_ROOT / config.query_set_path)

    assert sha256_bytes(serialize_query_set(query_set)) == config.query_set_sha256
    assert query_set.header.corpus_snapshot_path == config.corpus_snapshot_path
    assert query_set.header.corpus_snapshot_sha256 == config.corpus_snapshot_sha256


def test_shipped_query_split_is_frozen_at_sixteen_and_eight() -> None:
    config = load_evaluation_config(CONFIG_PATH)
    query_set = read_query_set(PROJECT_ROOT / config.query_set_path)

    development = [
        query for query in query_set.queries if query.split is EvaluationSplit.DEVELOPMENT
    ]
    test = [query for query in query_set.queries if query.split is EvaluationSplit.TEST]

    assert len(query_set.queries) == 24
    assert len(development) == 16
    assert len(test) == 8


def test_every_authored_pool_seed_exists_in_the_frozen_eligible_corpus() -> None:
    config = load_evaluation_config(CONFIG_PATH)
    query_set = read_query_set(PROJECT_ROOT / config.query_set_path)
    snapshot = read_dataset_snapshot(PROJECT_ROOT / config.corpus_snapshot_path)
    available = {
        f"github:{item.repository_id}:{item.path}"
        for item in snapshot.items
        if item.stored
        and item.validation_status in {ValidationStatus.VALID, ValidationStatus.WARNING}
    }
    seeds = {
        document_id for query in query_set.queries for document_id in query.pool_seed_document_ids
    }

    assert seeds <= available
    assert len(seeds) == 28


def test_formal_queries_do_not_reuse_manual_smoke_query_text() -> None:
    config = load_evaluation_config(CONFIG_PATH)
    query_set = read_query_set(PROJECT_ROOT / config.query_set_path)
    smoke_queries = {
        line.strip().casefold()
        for line in (PROJECT_ROOT / "data/evaluation/bm25-smoke-queries.txt")
        .read_text()
        .splitlines()
        if line.strip()
    }

    assert {query.query_text.casefold() for query in query_set.queries}.isdisjoint(smoke_queries)
