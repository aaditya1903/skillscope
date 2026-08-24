"""Strict configuration for frozen SkillScope retrieval evaluation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from skillscope.evaluation.data import Sha256

MAX_EVALUATION_CONFIG_BYTES = 64 * 1024


class EvaluationConfig(BaseModel):
    """Versioned paths, hashes, and cutoffs for one evaluation dataset."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=100)
    query_set_path: str = Field(min_length=1)
    query_set_sha256: Sha256
    qrels_path: str = Field(min_length=1)
    candidate_pool_path: str = Field(min_length=1)
    corpus_snapshot_path: str = Field(min_length=1)
    corpus_snapshot_sha256: Sha256
    bm25_config_path: str = Field(min_length=1)
    pool_depth: int = Field(ge=10, le=100)
    metric_cutoff: Literal[10] = 10
    relevance_threshold: Literal[1] = 1
    max_relevance_grade: Literal[2] = 2
    test_metrics_locked: Literal[True] = True

    @model_validator(mode="after")
    def validate_paths(self) -> EvaluationConfig:
        for field_name in (
            "query_set_path",
            "qrels_path",
            "candidate_pool_path",
            "corpus_snapshot_path",
        ):
            _validate_safe_relative_path(getattr(self, field_name), suffix=".jsonl")
        _validate_safe_relative_path(self.bm25_config_path, suffix=".json")
        return self


def load_evaluation_config(path: Path) -> EvaluationConfig:
    """Load one bounded, strict, versioned evaluation configuration."""

    try:
        payload = path.read_bytes()
    except OSError as error:
        raise ValueError(f"evaluation configuration could not be read: {path}") from error
    if not payload or len(payload) > MAX_EVALUATION_CONFIG_BYTES:
        raise ValueError("evaluation configuration has an invalid size")
    try:
        return EvaluationConfig.model_validate(json.loads(payload))
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError("evaluation configuration is invalid") from error


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
        raise ValueError(f"evaluation paths must be normalized safe relative {suffix} paths")
