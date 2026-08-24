"""Strict loading tests for the saved BM25 baseline parameters."""

import json
from pathlib import Path

import pytest

from skillscope.retrieval.config import load_bm25_config


def test_checked_in_baseline_configuration_is_valid() -> None:
    config = load_bm25_config(Path("config/retrieval/bm25-v1.json"))

    assert config.k1 == 1.5
    assert config.b == 0.75
    assert config.repeated_query_terms == "binary"
    assert config.eligible_validation_statuses == ("valid", "warning")
    assert config.corpus_snapshot_sha256 == (
        "d5f2c2ced677a468862edb25bbb8edea8b05ce63039916bbaeb02c7fb78c6562"
    )


def test_loader_rejects_unknown_fields_and_unsafe_snapshot_paths(tmp_path: Path) -> None:
    payload = json.loads(Path("config/retrieval/bm25-v1.json").read_text())
    payload["unexpected"] = True
    path = tmp_path / "unknown.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid"):
        load_bm25_config(path)

    payload.pop("unexpected")
    payload["corpus_snapshot_path"] = "../snapshot.jsonl"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="invalid"):
        load_bm25_config(path)


def test_loader_rejects_missing_or_oversized_configuration(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="could not be read"):
        load_bm25_config(tmp_path / "missing.json")

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (64 * 1024 + 1))
    with pytest.raises(ValueError, match="invalid size"):
        load_bm25_config(oversized)
