"""Canonical query and qrel datasets for reproducible retrieval evaluation."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from skillscope.db.enums import EvaluationSplit

QUERY_SET_SCHEMA_VERSION: Literal[1] = 1
QREL_SET_SCHEMA_VERSION: Literal[1] = 1
MIN_EVALUATION_QUERIES = 20
MAX_EVALUATION_QUERIES = 30
MAX_QUERY_FILE_BYTES = 256 * 1024
MAX_QREL_FILE_BYTES = 4 * 1024 * 1024
MAX_EVALUATION_RECORD_BYTES = 64 * 1024
MAX_QREL_JUDGEMENTS = 5_000

QueryId = Annotated[str, Field(pattern=r"^q[0-9]{3}$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
DocumentId = Annotated[str, Field(pattern=r"^github:[1-9][0-9]*:[^\x00\r\n]+$")]


class EvaluationDataError(ValueError):
    """An evaluation file violated its frozen-data contract."""


class EvaluationRecord(BaseModel):
    """Strict immutable base for evaluation JSONL records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class QuerySetHeader(EvaluationRecord):
    """Version and corpus identity stored at the start of a query set."""

    record_type: Literal["query_set"] = "query_set"
    schema_version: Literal[1] = QUERY_SET_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=100)
    corpus_snapshot_path: str = Field(min_length=1)
    corpus_snapshot_sha256: Sha256
    query_count: int = Field(ge=MIN_EVALUATION_QUERIES, le=MAX_EVALUATION_QUERIES)
    development_count: int = Field(ge=1, le=MAX_EVALUATION_QUERIES)
    test_count: int = Field(ge=1, le=MAX_EVALUATION_QUERIES)

    @field_validator("corpus_snapshot_path")
    @classmethod
    def validate_snapshot_path(cls, value: str) -> str:
        _validate_relative_path(value, suffix=".jsonl", label="corpus_snapshot_path")
        return value


class EvaluationQueryRecord(EvaluationRecord):
    """One frozen, realistically phrased information need."""

    record_type: Literal["query"] = "query"
    query_id: QueryId
    query_text: str = Field(min_length=3, max_length=200)
    category: str = Field(pattern=r"^[a-z][a-z0-9_]{1,49}$")
    split: EvaluationSplit
    intent: str = Field(min_length=10, max_length=500)
    pool_seed_document_ids: tuple[DocumentId, ...] = Field(min_length=1, max_length=5)

    @field_validator("query_text", "intent")
    @classmethod
    def validate_normalized_text(cls, value: str) -> str:
        if value != value.strip() or any(character in value for character in "\r\n\x00"):
            raise ValueError("query text fields must be trimmed single-line text")
        return value

    @field_validator("pool_seed_document_ids")
    @classmethod
    def validate_unique_pool_seeds(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) != len(value):
            raise ValueError("pool seed document IDs must be unique")
        for document_id in value:
            _validate_document_id(document_id)
        return value


@dataclass(frozen=True, slots=True)
class QuerySet:
    """A header plus ordered frozen development and test queries."""

    header: QuerySetHeader
    queries: tuple[EvaluationQueryRecord, ...]


class QrelSetHeader(EvaluationRecord):
    """Provenance and counts stored at the start of a qrel set."""

    record_type: Literal["qrel_set"] = "qrel_set"
    schema_version: Literal[1] = QREL_SET_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=100)
    query_set_path: str = Field(min_length=1)
    query_set_sha256: Sha256
    candidate_pool_path: str = Field(min_length=1)
    candidate_pool_sha256: Sha256
    corpus_snapshot_sha256: Sha256
    query_count: int = Field(ge=1, le=MAX_EVALUATION_QUERIES)
    judgement_count: int = Field(ge=1, le=MAX_QREL_JUDGEMENTS)
    relevant_judgement_count: int = Field(ge=1, le=MAX_QREL_JUDGEMENTS)
    relevance_threshold: Literal[1] = 1
    max_relevance_grade: Literal[2] = 2

    @field_validator("query_set_path", "candidate_pool_path")
    @classmethod
    def validate_evidence_path(cls, value: str) -> str:
        _validate_relative_path(value, suffix=".jsonl", label="evaluation evidence path")
        return value


class QrelRecord(EvaluationRecord):
    """One explicit, graded query-document relevance judgement."""

    record_type: Literal["qrel"] = "qrel"
    query_id: QueryId
    document_id: DocumentId
    content_sha256: Sha256
    relevance: int = Field(ge=0, le=2)
    rationale: str | None = Field(default=None, max_length=500)

    @field_validator("document_id")
    @classmethod
    def validate_stable_document_id(cls, value: str) -> str:
        _validate_document_id(value)
        return value

    @field_validator("rationale")
    @classmethod
    def validate_rationale(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or any(character in value for character in "\r\n\x00"):
            raise ValueError("rationale must be trimmed single-line text")
        if not value:
            raise ValueError("rationale cannot be empty")
        return value


@dataclass(frozen=True, slots=True)
class QrelSet:
    """A header plus canonical graded relevance judgements."""

    header: QrelSetHeader
    judgements: tuple[QrelRecord, ...]


def build_query_set(
    *,
    name: str,
    corpus_snapshot_path: str,
    corpus_snapshot_sha256: str,
    queries: tuple[EvaluationQueryRecord, ...],
) -> QuerySet:
    """Build and validate a canonical query set from authored records."""

    counts = Counter(query.split for query in queries)
    try:
        header = QuerySetHeader(
            name=name,
            corpus_snapshot_path=corpus_snapshot_path,
            corpus_snapshot_sha256=corpus_snapshot_sha256,
            query_count=len(queries),
            development_count=counts[EvaluationSplit.DEVELOPMENT],
            test_count=counts[EvaluationSplit.TEST],
        )
    except ValidationError as error:
        raise EvaluationDataError("query set must contain 20 to 30 queries") from error
    query_set = QuerySet(header=header, queries=queries)
    _validate_query_set(query_set)
    return query_set


def serialize_query_set(query_set: QuerySet) -> bytes:
    """Return canonical UTF-8 JSONL for one validated query set."""

    _validate_query_set(query_set)
    return _serialize_records((query_set.header, *query_set.queries))


def write_query_set(path: Path, query_set: QuerySet) -> None:
    """Atomically write a canonical query set to a safe relative path."""

    _validate_relative_path(path.as_posix(), suffix=".jsonl", label="query-set path")
    _write_atomic(path, serialize_query_set(query_set))


def read_query_set(path: Path) -> QuerySet:
    """Read a bounded query set and require canonical byte representation."""

    serialized = _read_bounded(path, maximum=MAX_QUERY_FILE_BYTES, label="query set")
    lines = _split_jsonl(serialized, maximum_records=MAX_EVALUATION_QUERIES + 1)
    try:
        query_set = QuerySet(
            header=QuerySetHeader.model_validate_json(lines[0]),
            queries=tuple(EvaluationQueryRecord.model_validate_json(line) for line in lines[1:]),
        )
    except (IndexError, ValidationError) as error:
        raise EvaluationDataError("query set contains an invalid record") from error
    _validate_query_set(query_set)
    if serialize_query_set(query_set) != serialized:
        raise EvaluationDataError("query set is not canonical JSONL")
    return query_set


def build_qrel_set(
    *,
    name: str,
    query_set_path: str,
    query_set_sha256: str,
    candidate_pool_path: str,
    candidate_pool_sha256: str,
    corpus_snapshot_sha256: str,
    judgements: tuple[QrelRecord, ...],
) -> QrelSet:
    """Build a qrel set with counts derived from its judgements."""

    query_ids = {judgement.query_id for judgement in judgements}
    relevant_count = sum(judgement.relevance >= 1 for judgement in judgements)
    qrels = QrelSet(
        header=QrelSetHeader(
            name=name,
            query_set_path=query_set_path,
            query_set_sha256=query_set_sha256,
            candidate_pool_path=candidate_pool_path,
            candidate_pool_sha256=candidate_pool_sha256,
            corpus_snapshot_sha256=corpus_snapshot_sha256,
            query_count=len(query_ids),
            judgement_count=len(judgements),
            relevant_judgement_count=relevant_count,
        ),
        judgements=judgements,
    )
    _validate_qrel_set(qrels)
    return qrels


def serialize_qrel_set(qrels: QrelSet) -> bytes:
    """Return canonical UTF-8 JSONL for one validated qrel set."""

    _validate_qrel_set(qrels)
    return _serialize_records((qrels.header, *qrels.judgements))


def write_qrel_set(path: Path, qrels: QrelSet) -> None:
    """Atomically write canonical qrels to a safe relative JSONL path."""

    _validate_relative_path(path.as_posix(), suffix=".jsonl", label="qrel path")
    _write_atomic(path, serialize_qrel_set(qrels))


def read_qrel_set(path: Path) -> QrelSet:
    """Read a bounded qrel set and require canonical byte representation."""

    serialized = _read_bounded(path, maximum=MAX_QREL_FILE_BYTES, label="qrel set")
    lines = _split_jsonl(serialized, maximum_records=MAX_QREL_JUDGEMENTS + 1)
    try:
        qrels = QrelSet(
            header=QrelSetHeader.model_validate_json(lines[0]),
            judgements=tuple(QrelRecord.model_validate_json(line) for line in lines[1:]),
        )
    except (IndexError, ValidationError) as error:
        raise EvaluationDataError("qrel set contains an invalid record") from error
    _validate_qrel_set(qrels)
    if serialize_qrel_set(qrels) != serialized:
        raise EvaluationDataError("qrel set is not canonical JSONL")
    return qrels


def validate_evaluation_dataset(
    query_set: QuerySet,
    qrels: QrelSet,
    *,
    query_set_sha256: str,
    available_documents: dict[str, str],
) -> None:
    """Cross-check queries, qrels, corpus identity, and document hashes."""

    if qrels.header.query_set_sha256 != query_set_sha256:
        raise EvaluationDataError("qrels reference different query-set bytes")
    if qrels.header.corpus_snapshot_sha256 != query_set.header.corpus_snapshot_sha256:
        raise EvaluationDataError("queries and qrels reference different corpus snapshots")

    expected_query_ids = {query.query_id for query in query_set.queries}
    judged_query_ids = {judgement.query_id for judgement in qrels.judgements}
    if judged_query_ids != expected_query_ids:
        raise EvaluationDataError("qrels must contain judgements for every frozen query")
    if qrels.header.query_count != len(expected_query_ids):
        raise EvaluationDataError("qrel query_count does not match the query set")

    positive_query_ids = {
        judgement.query_id for judgement in qrels.judgements if judgement.relevance >= 1
    }
    if positive_query_ids != expected_query_ids:
        raise EvaluationDataError("every query must have at least one relevant judgement")

    for judgement in qrels.judgements:
        content_sha256 = available_documents.get(judgement.document_id)
        if content_sha256 is None:
            raise EvaluationDataError(
                f"qrel references missing skill document ID: {judgement.document_id}"
            )
        if content_sha256 != judgement.content_sha256:
            raise EvaluationDataError(
                f"qrel content hash is stale for document ID: {judgement.document_id}"
            )


def sha256_bytes(serialized: bytes) -> str:
    """Return the lowercase SHA-256 digest for canonical evidence bytes."""

    return hashlib.sha256(serialized).hexdigest()


def _validate_query_set(query_set: QuerySet) -> None:
    queries = query_set.queries
    header = query_set.header
    if not MIN_EVALUATION_QUERIES <= len(queries) <= MAX_EVALUATION_QUERIES:
        raise EvaluationDataError("query set must contain 20 to 30 queries")
    if header.query_count != len(queries):
        raise EvaluationDataError("query_count does not match query records")
    counts = Counter(query.split for query in queries)
    if header.development_count != counts[EvaluationSplit.DEVELOPMENT]:
        raise EvaluationDataError("development_count does not match query records")
    if header.test_count != counts[EvaluationSplit.TEST]:
        raise EvaluationDataError("test_count does not match query records")
    if header.development_count + header.test_count != header.query_count:
        raise EvaluationDataError("query split counts do not reconcile")
    query_ids = [query.query_id for query in queries]
    if query_ids != sorted(query_ids) or len(set(query_ids)) != len(query_ids):
        raise EvaluationDataError("queries must have unique, ascending query IDs")
    normalized_texts = [query.query_text.casefold() for query in queries]
    if len(set(normalized_texts)) != len(normalized_texts):
        raise EvaluationDataError("query texts must be unique case-insensitively")


def _validate_qrel_set(qrels: QrelSet) -> None:
    judgements = qrels.judgements
    header = qrels.header
    if not judgements or len(judgements) > MAX_QREL_JUDGEMENTS:
        raise EvaluationDataError("qrel set has an invalid judgement count")
    if header.judgement_count != len(judgements):
        raise EvaluationDataError("judgement_count does not match qrel records")
    relevant_count = sum(judgement.relevance >= 1 for judgement in judgements)
    if header.relevant_judgement_count != relevant_count:
        raise EvaluationDataError("relevant_judgement_count does not match qrel records")
    keys = [(judgement.query_id, judgement.document_id) for judgement in judgements]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise EvaluationDataError("qrels must have unique, ascending query-document keys")
    query_count = len({judgement.query_id for judgement in judgements})
    if header.query_count != query_count:
        raise EvaluationDataError("qrel query_count does not match qrel records")
    for judgement in judgements:
        if judgement.relevance >= 1 and judgement.rationale is None:
            raise EvaluationDataError("relevant judgements require a rationale")


def _serialize_records(records: tuple[EvaluationRecord, ...]) -> bytes:
    lines = (
        json.dumps(
            record.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for record in records
    )
    return ("\n".join(lines) + "\n").encode("utf-8")


def _read_bounded(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        serialized = path.read_bytes()
    except OSError as error:
        raise EvaluationDataError(f"{label} could not be read: {path}") from error
    if not serialized or len(serialized) > maximum:
        raise EvaluationDataError(f"{label} is empty or exceeds its safety limit")
    return serialized


def _split_jsonl(serialized: bytes, *, maximum_records: int) -> list[bytes]:
    if not serialized.endswith(b"\n"):
        raise EvaluationDataError("evaluation JSONL must end with a newline")
    lines = serialized.splitlines()
    if len(lines) > maximum_records:
        raise EvaluationDataError("evaluation JSONL exceeds its record limit")
    if any(not line or len(line) > MAX_EVALUATION_RECORD_BYTES for line in lines):
        raise EvaluationDataError("evaluation JSONL contains an invalid record size")
    return lines


def _write_atomic(path: Path, serialized: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        assert temporary_path is not None
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _validate_relative_path(value: str, *, suffix: str, label: str) -> None:
    path = Path(value)
    if (
        path.is_absolute()
        or path.suffix != suffix
        or ".." in path.parts
        or not value
        or value.startswith("./")
        or path.as_posix() != value
    ):
        raise ValueError(f"{label} must be a normalized safe relative {suffix} path")


def _validate_document_id(value: str) -> None:
    _, repository_id, path_value = value.split(":", maxsplit=2)
    path = Path(path_value)
    if (
        not repository_id.isdigit()
        or repository_id.startswith("0")
        or path.is_absolute()
        or ".." in path.parts
        or not path_value
        or path_value.startswith("./")
        or path.as_posix() != path_value
    ):
        raise ValueError("document ID must contain a stable repository ID and safe path")
