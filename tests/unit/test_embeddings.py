"""Deterministic embedding-text and vector-contract tests."""

from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import numpy as np
import pytest

from skillscope.db.enums import ValidationStatus
from skillscope.retrieval.config import DenseHybridConfig
from skillscope.retrieval.corpus import CorpusDocument, LexicalFields
from skillscope.retrieval.embeddings import (
    EmbeddingContractError,
    SentenceTransformerEncoder,
    validate_embedding_matrix,
)


def _config() -> DenseHybridConfig:
    return DenseHybridConfig(
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="1" * 40,
        sentence_transformers_version="6.0.0",
        batch_size=16,
        default_top_k=10,
        bm25_weight=1.0,
        dense_weight=1.0,
        corpus_snapshot_path="data/manifests/test.jsonl",
        corpus_snapshot_sha256="a" * 64,
        bm25_config_path="config/retrieval/bm25.json",
        bm25_config_sha256="b" * 64,
        eligible_validation_statuses=("valid", "warning"),
    )


def test_embedding_text_is_labelled_stable_and_hash_bound() -> None:
    document = CorpusDocument(
        document_id="github:1:skills/alpha/SKILL.md",
        skill_id=UUID(int=1),
        repository_id=1,
        repository_full_name="example/catalogue",
        path="skills/alpha/SKILL.md",
        name="alpha",
        safe_snippet="Synthetic.",
        validation_status=ValidationStatus.VALID,
        content_sha256="a" * 64,
        fields=LexicalFields("alpha", "build tables", "mit", "usage", "body steps"),
        tokens=("alpha",),
    )

    assert document.embedding_text == (
        "name: alpha\ndescription: build tables\nmetadata: mit\nheadings: usage\nbody: body steps"
    )
    assert len(document.embedding_text_sha256) == 64
    changed = replace(
        document,
        fields=LexicalFields("alpha", "build charts", "mit", "usage", "body steps"),
    )
    assert changed.embedding_text_sha256 != document.embedding_text_sha256


@pytest.mark.parametrize(
    "matrix",
    [
        np.zeros((1, 384), dtype=np.float32),
        np.ones((1, 383), dtype=np.float32),
        np.full((1, 384), np.nan, dtype=np.float32),
        np.ones((1, 384), dtype=np.float32),
    ],
)
def test_vector_validation_rejects_zero_wrong_nonfinite_or_unnormalized(
    matrix: np.ndarray,
) -> None:
    with pytest.raises(EmbeddingContractError):
        validate_embedding_matrix(
            matrix,
            expected_rows=1,
            dimension=384,
            require_unit_norm=True,
        )


def test_vector_validation_accepts_normalized_float_matrix() -> None:
    matrix = np.zeros((2, 384), dtype=np.float32)
    matrix[0, 0] = 1.0
    matrix[1, 1] = 1.0

    validate_embedding_matrix(
        matrix,
        expected_rows=2,
        dimension=384,
        require_unit_norm=True,
    )


def test_sentence_transformer_service_loads_once_and_passes_safe_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeModel:
        max_seq_length = 256

        def __init__(self, model_id: str, **options: object) -> None:
            calls.append({"model_id": model_id, **options})

        def get_sentence_embedding_dimension(self) -> int:
            return 384

        def encode(self, texts: list[str], **options: object) -> np.ndarray:
            vector = np.zeros((len(texts), 384), dtype=np.float32)
            vector[:, 0] = 1.0
            return vector

    def fake_import(name: str) -> Any:
        assert name == "sentence_transformers"
        return SimpleNamespace(SentenceTransformer=FakeModel)

    monkeypatch.setattr("importlib.metadata.version", lambda _: "6.0.0")
    monkeypatch.setattr("importlib.import_module", fake_import)
    encoder = SentenceTransformerEncoder(_config())

    first = encoder.encode(("alpha",), batch_size=1)
    second = encoder.encode(("beta",), batch_size=1)

    assert first.shape == second.shape == (1, 384)
    assert len(calls) == 1
    assert calls[0] == {
        "model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "revision": "1" * 40,
        "device": "cpu",
        "trust_remote_code": False,
    }


def test_sentence_transformer_service_requires_the_pinned_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("importlib.metadata.version", lambda _: "5.0.0")
    encoder = SentenceTransformerEncoder(_config())

    with pytest.raises(EmbeddingContractError, match="runtime differs"):
        encoder.encode(("alpha",), batch_size=1)
