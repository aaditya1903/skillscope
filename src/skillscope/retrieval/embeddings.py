"""Pinned local embedding service and content-hash-bound indexing."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from threading import Lock
from typing import Any, Protocol

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from skillscope.db.models import Skill
from skillscope.retrieval.config import DEMONSTRATION_MODEL_ID, DenseHybridConfig
from skillscope.retrieval.corpus import FrozenCorpus, StaleCorpusError
from skillscope.retrieval.text import tokenize

UNIT_NORM_ABSOLUTE_TOLERANCE = 1e-4


class EmbeddingContractError(ValueError):
    """An encoder output or stored provenance violated the pinned contract."""


class EmbeddingEncoder(Protocol):
    """Minimal dependency boundary used by production and deterministic tests."""

    model_id: str
    model_revision: str
    dimension: int

    def encode(self, texts: Sequence[str], *, batch_size: int) -> np.ndarray:
        """Return one normalized float vector per input text."""


class SentenceTransformerEncoder:
    """Lazily load the pinned model once and encode on deterministic CPU settings."""

    def __init__(self, config: DenseHybridConfig) -> None:
        self.config = config
        self.model_id: str = config.model_id
        self.model_revision: str = config.model_revision
        self.dimension: int = config.model_dimension
        self._model: Any | None = None
        self._model_load_lock = Lock()

    def encode(self, texts: Sequence[str], *, batch_size: int) -> np.ndarray:
        """Encode inert text without prompts, remote code, or model mutation."""

        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        if not 1 <= batch_size <= 128:
            raise EmbeddingContractError("embedding batch size must be between 1 and 128")

        model = self._load_model()
        raw_embeddings = model.encode(
            list(texts),
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=self.config.normalize_embeddings,
        )
        embeddings = np.asarray(raw_embeddings, dtype=np.float32)
        validate_embedding_matrix(
            embeddings,
            expected_rows=len(texts),
            dimension=self.dimension,
            require_unit_norm=self.config.normalize_embeddings,
        )
        return embeddings

    def _load_model(self) -> Any:
        if self._model is not None:
            return self._model

        with self._model_load_lock:
            if self._model is None:
                self._model = self._create_model()
        return self._model

    def _create_model(self) -> Any:
        """Load and validate the pinned model while holding the initialization lock."""

        try:
            installed_version = importlib.metadata.version("sentence-transformers")
        except importlib.metadata.PackageNotFoundError as error:
            raise EmbeddingContractError(
                "the local model runtime is not installed; run with uv --extra model"
            ) from error
        if installed_version != self.config.sentence_transformers_version:
            raise EmbeddingContractError(
                "sentence-transformers runtime differs from the pinned retrieval configuration"
            )

        try:
            sentence_transformers = importlib.import_module("sentence_transformers")
        except ModuleNotFoundError as error:
            raise EmbeddingContractError(
                "the local model runtime is not installed; run with uv --extra model"
            ) from error
        model_class: Any = sentence_transformers.SentenceTransformer
        model = model_class(
            self.model_id,
            revision=self.model_revision,
            device=self.config.device,
            trust_remote_code=self.config.trust_remote_code,
        )
        dimension = model.get_sentence_embedding_dimension()
        if dimension != self.dimension:
            raise EmbeddingContractError(
                f"embedding model returned dimension {dimension}; expected {self.dimension}"
            )
        if model.max_seq_length != self.config.max_sequence_length:
            raise EmbeddingContractError(
                "embedding model sequence length differs from the pinned configuration"
            )
        return model


class HashingDemonstrationEncoder:
    """Deterministic token-hashing encoder for the token-free demonstration corpus.

    It lets a clean clone exercise dense and hybrid retrieval without a model
    download, and it is reproducible because a token always hashes to the same
    coordinates. It is a bag-of-words projection with no learned semantics, so
    it is never used for an evaluation report and never compared with the
    measured retrieval quality of the pinned local model.
    """

    def __init__(self, config: DenseHybridConfig) -> None:
        if config.uses_evaluated_model:
            raise EmbeddingContractError(
                "the demonstration encoder cannot serve the evaluated model configuration"
            )
        self.config = config
        self.model_id: str = config.model_id
        self.model_revision: str = config.model_revision
        self.dimension: int = config.model_dimension

    def encode(self, texts: Sequence[str], *, batch_size: int) -> np.ndarray:
        """Project tokenized text onto fixed hashed coordinates and unit-normalize."""

        if not texts:
            return np.empty((0, self.dimension), dtype=np.float32)
        if not 1 <= batch_size <= 128:
            raise EmbeddingContractError("embedding batch size must be between 1 and 128")

        embeddings = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "big") % self.dimension
                sign = 1.0 if digest[4] & 1 else -1.0
                embeddings[row, index] += sign
            norm = float(np.linalg.norm(embeddings[row]))
            # A document with no tokens cannot be placed, so pin it to one axis
            # rather than emitting a zero vector the unit-norm check rejects.
            if norm == 0.0:
                embeddings[row, 0] = 1.0
            else:
                embeddings[row] /= norm

        validate_embedding_matrix(
            embeddings,
            expected_rows=len(texts),
            dimension=self.dimension,
            require_unit_norm=True,
        )
        return embeddings


@lru_cache(maxsize=4)
def get_sentence_transformer_encoder(config: DenseHybridConfig) -> SentenceTransformerEncoder:
    """Return one lazily loaded model service per immutable configuration."""

    return SentenceTransformerEncoder(config)


@lru_cache(maxsize=4)
def get_encoder(config: DenseHybridConfig) -> EmbeddingEncoder:
    """Return the encoder the configuration pins, without importing an unused runtime."""

    if config.model_id == DEMONSTRATION_MODEL_ID:
        return HashingDemonstrationEncoder(config)
    return get_sentence_transformer_encoder(config)


@dataclass(frozen=True, slots=True)
class EmbeddingIndexSummary:
    """Reconciled evidence from one idempotent frozen-corpus indexing run."""

    corpus_size: int
    indexed_count: int
    unchanged_count: int
    model_id: str
    model_revision: str
    model_dimension: int
    embedding_config_sha256: str
    corpus_snapshot_sha256: str


def index_frozen_corpus_embeddings(
    session: Session,
    corpus: FrozenCorpus,
    config: DenseHybridConfig,
    encoder: EmbeddingEncoder,
    *,
    embedding_config_sha256: str,
    indexed_at: datetime | None = None,
) -> EmbeddingIndexSummary:
    """Index stale documents in batches and leave current embeddings untouched."""

    _validate_config_and_encoder(
        corpus,
        config,
        encoder,
        embedding_config_sha256=embedding_config_sha256,
    )
    documents_by_skill_id = {document.skill_id: document for document in corpus.documents}
    skills = session.scalars(select(Skill).where(Skill.id.in_(documents_by_skill_id))).all()
    skills_by_id = {skill.id: skill for skill in skills}
    if set(skills_by_id) != set(documents_by_skill_id):
        raise StaleCorpusError("database skills changed after the frozen corpus was loaded")

    stale_documents = tuple(
        document
        for document in corpus.documents
        if not _embedding_is_current(
            skills_by_id[document.skill_id],
            document_content_sha256=document.content_sha256,
            embedding_text_sha256=document.embedding_text_sha256,
            config=config,
            embedding_config_sha256=embedding_config_sha256,
        )
    )
    timestamp = indexed_at or datetime.now(UTC)
    for start in range(0, len(stale_documents), config.batch_size):
        batch = stale_documents[start : start + config.batch_size]
        embeddings = encoder.encode(
            tuple(document.embedding_text for document in batch),
            batch_size=config.batch_size,
        )
        validate_embedding_matrix(
            embeddings,
            expected_rows=len(batch),
            dimension=config.model_dimension,
            require_unit_norm=config.normalize_embeddings,
        )
        for document, vector in zip(batch, embeddings, strict=True):
            skill = skills_by_id[document.skill_id]
            skill.embedding = [float(value) for value in vector]
            skill.embedding_model_id = config.model_id
            skill.embedding_model_revision = config.model_revision
            skill.embedding_config_sha256 = embedding_config_sha256
            skill.embedding_content_sha256 = document.content_sha256
            skill.embedding_text_sha256 = document.embedding_text_sha256
            skill.indexed_at = timestamp
        session.flush()

    return EmbeddingIndexSummary(
        corpus_size=len(corpus.documents),
        indexed_count=len(stale_documents),
        unchanged_count=len(corpus.documents) - len(stale_documents),
        model_id=config.model_id,
        model_revision=config.model_revision,
        model_dimension=config.model_dimension,
        embedding_config_sha256=embedding_config_sha256,
        corpus_snapshot_sha256=corpus.snapshot_sha256,
    )


def validate_embedding_matrix(
    embeddings: np.ndarray,
    *,
    expected_rows: int,
    dimension: int,
    require_unit_norm: bool,
) -> None:
    """Reject wrong-shaped, non-finite, zero, or non-normalized vectors."""

    if embeddings.shape != (expected_rows, dimension):
        raise EmbeddingContractError(
            f"embedding matrix has shape {embeddings.shape}; expected {(expected_rows, dimension)}"
        )
    if not np.issubdtype(embeddings.dtype, np.floating):
        raise EmbeddingContractError("embedding matrix must contain floating-point values")
    if not np.isfinite(embeddings).all():
        raise EmbeddingContractError("embedding matrix contains non-finite values")
    norms = np.linalg.norm(embeddings, axis=1)
    if np.any(norms <= 0.0):
        raise EmbeddingContractError("embedding matrix contains a zero vector")
    if require_unit_norm and not np.allclose(
        norms,
        1.0,
        rtol=0.0,
        atol=UNIT_NORM_ABSOLUTE_TOLERANCE,
    ):
        raise EmbeddingContractError("embedding vectors are not normalized to unit length")


def _validate_config_and_encoder(
    corpus: FrozenCorpus,
    config: DenseHybridConfig,
    encoder: EmbeddingEncoder,
    *,
    embedding_config_sha256: str,
) -> None:
    if corpus.snapshot_sha256 != config.corpus_snapshot_sha256:
        raise StaleCorpusError("dense configuration references a different corpus snapshot")
    if len(embedding_config_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in embedding_config_sha256
    ):
        raise EmbeddingContractError("embedding configuration SHA-256 is invalid")
    if (
        encoder.model_id != config.model_id
        or encoder.model_revision != config.model_revision
        or encoder.dimension != config.model_dimension
    ):
        raise EmbeddingContractError("embedding encoder differs from the pinned configuration")


def _embedding_is_current(
    skill: Skill,
    *,
    document_content_sha256: str,
    embedding_text_sha256: str,
    config: DenseHybridConfig,
    embedding_config_sha256: str,
) -> bool:
    return (
        skill.embedding is not None
        and skill.embedding_model_id == config.model_id
        and skill.embedding_model_revision == config.model_revision
        and skill.embedding_config_sha256 == embedding_config_sha256
        and skill.embedding_content_sha256 == document_content_sha256
        and skill.embedding_text_sha256 == embedding_text_sha256
        and skill.indexed_at is not None
    )
