"""Versioned retrieval-evaluation configuration tests."""

import json
from pathlib import Path

import pytest

from skillscope.evaluation.config import load_evaluation_config


def _payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "name": "test-evaluation",
        "query_set_path": "data/evaluation/queries.jsonl",
        "query_set_sha256": "a" * 64,
        "qrels_path": "data/evaluation/qrels.jsonl",
        "candidate_pool_path": "data/evaluation/pool.jsonl",
        "corpus_snapshot_path": "data/manifests/snapshot.jsonl",
        "corpus_snapshot_sha256": "b" * 64,
        "bm25_config_path": "config/retrieval/bm25.json",
        "pool_depth": 20,
        "metric_cutoff": 10,
        "relevance_threshold": 1,
        "max_relevance_grade": 2,
        "test_metrics_locked": True,
    }


def test_loads_strict_evaluation_config(tmp_path: Path) -> None:
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps(_payload()))

    config = load_evaluation_config(path)

    assert config.pool_depth == 20
    assert config.metric_cutoff == 10
    assert config.test_metrics_locked is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("query_set_path", "../queries.jsonl"),
        ("qrels_path", "/tmp/qrels.jsonl"),
        ("bm25_config_path", "config/retrieval/bm25.toml"),
    ],
)
def test_rejects_unsafe_or_wrong_extension_paths(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    payload = _payload()
    payload[field] = value
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="configuration is invalid"):
        load_evaluation_config(path)


def test_rejects_unknown_configuration_fields(tmp_path: Path) -> None:
    payload = _payload()
    payload["surprise"] = True
    path = tmp_path / "evaluation.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="configuration is invalid"):
        load_evaluation_config(path)
