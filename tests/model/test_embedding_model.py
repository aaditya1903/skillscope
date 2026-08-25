"""Opt-in smoke test for the exact pinned Hugging Face model revision."""

import os
from pathlib import Path

import numpy as np
import pytest

from skillscope.retrieval.config import load_dense_hybrid_config
from skillscope.retrieval.embeddings import SentenceTransformerEncoder

pytestmark = [
    pytest.mark.model,
    pytest.mark.skipif(
        os.environ.get("SKILLSCOPE_RUN_MODEL_SMOKE") != "1",
        reason="set SKILLSCOPE_RUN_MODEL_SMOKE=1 and install the model extra",
    ),
]


def test_pinned_model_returns_normalized_384_dimensional_vectors() -> None:
    config = load_dense_hybrid_config(Path("config/retrieval/dense-hybrid-v1.json"))
    encoder = SentenceTransformerEncoder(config)

    embeddings = encoder.encode(
        ("create and edit spreadsheets", "build an MCP server"),
        batch_size=2,
    )

    assert embeddings.shape == (2, 384)
    assert np.linalg.norm(embeddings, axis=1) == pytest.approx((1.0, 1.0), abs=1e-4)
    assert not np.allclose(embeddings[0], embeddings[1])
