"""Tests for the deterministic encoder used by the demonstration corpus."""

from __future__ import annotations

import hashlib

import numpy as np
import pytest

from skillscope.retrieval.config import DEMONSTRATION_MODEL_ID, DenseHybridConfig
from skillscope.retrieval.embeddings import (
    EmbeddingContractError,
    HashingDemonstrationEncoder,
    get_encoder,
)

SNAPSHOT_SHA = "a" * 64


def _config(model_id: str) -> DenseHybridConfig:
    evaluated = model_id != DEMONSTRATION_MODEL_ID
    return DenseHybridConfig(
        model_id=model_id,  # type: ignore[arg-type]
        model_revision="b" * 40,
        sentence_transformers_version="6.0.0" if evaluated else None,
        batch_size=8,
        default_top_k=10,
        bm25_weight=1.0,
        dense_weight=1.0,
        corpus_snapshot_path="data/demo/generated/dataset-snapshot.jsonl",
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        bm25_config_path="config/demo/bm25-v1.json",
        bm25_config_sha256=hashlib.sha256(b"bm25").hexdigest(),
        eligible_validation_statuses=("valid", "warning"),
    )


def test_encoder_is_deterministic_and_unit_normalized() -> None:
    encoder = HashingDemonstrationEncoder(_config(DEMONSTRATION_MODEL_ID))

    first = encoder.encode(("review a code diff", "build a spreadsheet"), batch_size=8)
    second = encoder.encode(("review a code diff", "build a spreadsheet"), batch_size=8)

    assert first.shape == (2, 384)
    assert np.array_equal(first, second)
    assert np.allclose(np.linalg.norm(first, axis=1), 1.0, atol=1e-4)


def test_encoder_places_empty_text_without_emitting_a_zero_vector() -> None:
    encoder = HashingDemonstrationEncoder(_config(DEMONSTRATION_MODEL_ID))

    embeddings = encoder.encode(("",), batch_size=8)

    assert np.isclose(float(np.linalg.norm(embeddings[0])), 1.0, atol=1e-4)


def test_encoder_separates_unrelated_text() -> None:
    encoder = HashingDemonstrationEncoder(_config(DEMONSTRATION_MODEL_ID))

    matrix = encoder.encode(
        ("review a code diff", "review a code diff carefully", "spreadsheet workbook charts"),
        batch_size=8,
    )

    assert float(matrix[0] @ matrix[1]) > float(matrix[0] @ matrix[2])


def test_encoder_refuses_to_serve_the_evaluated_configuration() -> None:
    with pytest.raises(EmbeddingContractError, match="evaluated model configuration"):
        HashingDemonstrationEncoder(_config("sentence-transformers/all-MiniLM-L6-v2"))


def test_encoder_selection_follows_the_pinned_model_identifier() -> None:
    demonstration = get_encoder(_config(DEMONSTRATION_MODEL_ID))

    assert isinstance(demonstration, HashingDemonstrationEncoder)
    assert demonstration.model_id == DEMONSTRATION_MODEL_ID


def test_dense_configuration_requires_a_runtime_version_only_for_the_real_model() -> None:
    with pytest.raises(ValueError, match="requires a pinned runtime version"):
        DenseHybridConfig(
            model_id="sentence-transformers/all-MiniLM-L6-v2",
            model_revision="b" * 40,
            sentence_transformers_version=None,
            batch_size=8,
            default_top_k=10,
            bm25_weight=1.0,
            dense_weight=1.0,
            corpus_snapshot_path="data/manifests/dataset-snapshot.jsonl",
            corpus_snapshot_sha256=SNAPSHOT_SHA,
            bm25_config_path="config/retrieval/bm25-v1.json",
            bm25_config_sha256=hashlib.sha256(b"bm25").hexdigest(),
            eligible_validation_statuses=("valid", "warning"),
        )

    with pytest.raises(ValueError, match="must not pin a model runtime version"):
        DenseHybridConfig(
            model_id=DEMONSTRATION_MODEL_ID,
            model_revision="b" * 40,
            sentence_transformers_version="6.0.0",
            batch_size=8,
            default_top_k=10,
            bm25_weight=1.0,
            dense_weight=1.0,
            corpus_snapshot_path="data/demo/generated/dataset-snapshot.jsonl",
            corpus_snapshot_sha256=SNAPSHOT_SHA,
            bm25_config_path="config/demo/bm25-v1.json",
            bm25_config_sha256=hashlib.sha256(b"bm25").hexdigest(),
            eligible_validation_statuses=("valid", "warning"),
        )
