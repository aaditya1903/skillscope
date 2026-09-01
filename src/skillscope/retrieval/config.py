"""Strict configuration for reproducible lexical, dense, and hybrid retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from skillscope.retrieval.text import TOKENIZER_VERSION

MAX_BASELINE_CONFIG_BYTES = 64 * 1024
MAX_DENSE_HYBRID_CONFIG_BYTES = 64 * 1024

EVALUATED_MODEL_ID = "sentence-transformers/all-MiniLM-L6-v2"
# A deterministic hashing encoder used only by the token-free demonstration
# corpus, so a clean clone can exercise dense and hybrid search without
# downloading a model. It produces no comparable retrieval quality and is never
# used for an evaluation report.
DEMONSTRATION_MODEL_ID = "skillscope/demonstration-hashing-v1"


class BM25BaselineConfig(BaseModel):
    """Versioned parameters and corpus identity for one lexical baseline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    method: Literal["bm25"] = "bm25"
    k1: float = Field(gt=0.0, le=10.0)
    b: float = Field(ge=0.0, le=1.0)
    default_top_k: int = Field(ge=1, le=100)
    repeated_query_terms: Literal["binary"] = "binary"
    tokenizer_version: Literal["unicode-nfkc-markdown-v1"] = TOKENIZER_VERSION
    corpus_snapshot_path: str = Field(min_length=1)
    corpus_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_validation_statuses: tuple[Literal["valid", "warning"], ...]

    @model_validator(mode="after")
    def validate_corpus_contract(self) -> BM25BaselineConfig:
        path = Path(self.corpus_snapshot_path)
        if path.is_absolute() or ".." in path.parts or path.suffix != ".jsonl":
            raise ValueError("corpus_snapshot_path must be a safe relative JSONL path")
        if self.eligible_validation_statuses != ("valid", "warning"):
            raise ValueError("the baseline corpus must contain valid and warning skills")
        return self


def load_bm25_config(path: Path) -> BM25BaselineConfig:
    """Load one bounded, strict, versioned BM25 configuration file."""

    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ValueError(f"BM25 configuration could not be read: {path}") from error
    if not payload or len(payload) > MAX_BASELINE_CONFIG_BYTES:
        raise ValueError("BM25 configuration has an invalid size")
    try:
        decoded = json.loads(payload)
        return BM25BaselineConfig.model_validate(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError("BM25 configuration is invalid") from error


class DenseHybridConfig(BaseModel):
    """Pinned model, corpus, exact-search, and RRF configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    method: Literal["dense_hybrid"] = "dense_hybrid"
    model_id: Literal[
        "sentence-transformers/all-MiniLM-L6-v2",
        "skillscope/demonstration-hashing-v1",
    ]
    model_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    sentence_transformers_version: str | None = Field(
        default=None,
        pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$",
    )
    model_dimension: Literal[384] = 384
    max_sequence_length: Literal[256] = 256
    normalize_embeddings: Literal[True] = True
    device: Literal["cpu"] = "cpu"
    trust_remote_code: Literal[False] = False
    text_version: Literal["labelled-retrieval-fields-v1"] = "labelled-retrieval-fields-v1"
    batch_size: int = Field(ge=1, le=128)
    distance: Literal["cosine"] = "cosine"
    exact_search: Literal[True] = True
    default_top_k: int = Field(ge=1, le=50)
    rrf_candidate_depth: Literal[50] = 50
    rrf_k: Literal[60] = 60
    bm25_weight: float = Field(gt=0.0, le=10.0)
    dense_weight: float = Field(gt=0.0, le=10.0)
    corpus_snapshot_path: str = Field(min_length=1)
    corpus_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bm25_config_path: str = Field(min_length=1)
    bm25_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    eligible_validation_statuses: tuple[Literal["valid", "warning"], ...]

    @property
    def uses_evaluated_model(self) -> bool:
        """Report whether this configuration pins the evaluated local model."""

        return self.model_id == EVALUATED_MODEL_ID

    @model_validator(mode="after")
    def validate_retrieval_contract(self) -> DenseHybridConfig:
        _validate_safe_relative_path(self.corpus_snapshot_path, suffix=".jsonl")
        _validate_safe_relative_path(self.bm25_config_path, suffix=".json")
        if self.uses_evaluated_model and self.sentence_transformers_version is None:
            raise ValueError("the evaluated model requires a pinned runtime version")
        if not self.uses_evaluated_model and self.sentence_transformers_version is not None:
            raise ValueError("the demonstration encoder must not pin a model runtime version")
        if self.eligible_validation_statuses != ("valid", "warning"):
            raise ValueError("dense retrieval must use the frozen valid and warning corpus")
        if self.default_top_k > self.rrf_candidate_depth:
            raise ValueError("default_top_k cannot exceed the RRF candidate depth")
        return self


def load_dense_hybrid_config(path: Path) -> DenseHybridConfig:
    """Load one bounded, strict, versioned dense/hybrid configuration."""

    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ValueError(f"dense/hybrid configuration could not be read: {path}") from error
    if not payload or len(payload) > MAX_DENSE_HYBRID_CONFIG_BYTES:
        raise ValueError("dense/hybrid configuration has an invalid size")
    try:
        return DenseHybridConfig.model_validate(json.loads(payload))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError("dense/hybrid configuration is invalid") from error


def _validate_safe_relative_path(value: str, *, suffix: str) -> None:
    path = Path(value)
    if (
        path.is_absolute()
        or path.suffix != suffix
        or ".." in path.parts
        or not value
        or value.startswith("./")
        or path.as_posix() != value
    ):
        raise ValueError(f"retrieval path must be a normalized safe relative {suffix} path")
