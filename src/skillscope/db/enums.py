"""Stable categorical values shared by persistence and domain layers."""

from enum import StrEnum


class LicenseStatus(StrEnum):
    PERMISSIVE = "permissive"
    RESTRICTIVE = "restrictive"
    MISSING = "missing"
    UNKNOWN = "unknown"


class ValidationStatus(StrEnum):
    VALID = "valid"
    WARNING = "warning"
    INVALID = "invalid"


class SupportingFileType(StrEnum):
    SCRIPT = "script"
    REFERENCE = "reference"
    ASSET = "asset"
    OTHER = "other"


class IngestionRunStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionItemStatus(StrEnum):
    INGESTED = "ingested"
    UNCHANGED = "unchanged"
    SKIPPED = "skipped"
    INVALID = "invalid"
    ERROR = "error"


class EvaluationSplit(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"


class RetrievalMethod(StrEnum):
    BM25 = "bm25"
    DENSE = "dense"
    HYBRID = "hybrid"
