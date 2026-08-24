"""Strict configuration for the reproducible BM25 baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from skillscope.retrieval.text import TOKENIZER_VERSION

MAX_BASELINE_CONFIG_BYTES = 64 * 1024


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
