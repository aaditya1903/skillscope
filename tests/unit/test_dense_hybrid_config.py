"""Strict loading tests for the pinned dense and hybrid configuration."""

import json
from pathlib import Path

import pytest

from skillscope.retrieval.config import load_dense_hybrid_config


def _payload() -> dict[str, object]:
    return json.loads(Path("config/retrieval/dense-hybrid-v1.json").read_text())


def test_checked_in_dense_hybrid_configuration_is_fully_pinned() -> None:
    config = load_dense_hybrid_config(Path("config/retrieval/dense-hybrid-v1.json"))

    assert config.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert config.model_revision == "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    assert config.sentence_transformers_version == "6.0.0"
    assert config.model_dimension == 384
    assert config.max_sequence_length == 256
    assert config.normalize_embeddings is True
    assert config.trust_remote_code is False
    assert config.exact_search is True
    assert config.rrf_candidate_depth == 50
    assert config.rrf_k == 60
    assert config.bm25_weight == config.dense_weight == 1.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("model_revision", "main"),
        ("model_dimension", 768),
        ("normalize_embeddings", False),
        ("exact_search", False),
        ("rrf_candidate_depth", 20),
        ("corpus_snapshot_path", "../snapshot.jsonl"),
        ("bm25_config_path", "/tmp/bm25.json"),
        ("eligible_validation_statuses", ["valid"]),
    ],
)
def test_loader_rejects_unpinned_or_unsafe_contracts(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    payload = _payload()
    payload[field] = value
    path = tmp_path / "dense.json"
    path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="configuration is invalid"):
        load_dense_hybrid_config(path)


def test_loader_rejects_unknown_fields_and_oversized_files(tmp_path: Path) -> None:
    payload = _payload()
    payload["unexpected"] = True
    path = tmp_path / "dense.json"
    path.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="configuration is invalid"):
        load_dense_hybrid_config(path)

    path.write_bytes(b"x" * (64 * 1024 + 1))
    with pytest.raises(ValueError, match="invalid size"):
        load_dense_hybrid_config(path)
