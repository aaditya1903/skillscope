"""Deterministic candidate pooling and rank-blinded labelling worksheets."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from skillscope.db.enums import ValidationStatus
from skillscope.evaluation.data import (
    DocumentId,
    EvaluationDataError,
    EvaluationQueryRecord,
    QrelRecord,
    QrelSet,
    QueryId,
    QuerySet,
    Sha256,
    build_qrel_set,
)
from skillscope.retrieval.bm25 import BM25Index
from skillscope.retrieval.corpus import CorpusDocument, StaleCorpusError

POOL_SCHEMA_VERSION: Literal[1] = 1
WORKSHEET_SCHEMA_VERSION = "1"
BLINDING_VERSION: Literal["sha256-query-document-v1"] = "sha256-query-document-v1"
MAX_POOL_BYTES = 8 * 1024 * 1024
MAX_WORKSHEET_BYTES = 16 * 1024 * 1024
MAX_POOL_ITEMS = 3_000

WORKSHEET_COLUMNS = (
    "schema_version",
    "query_set_sha256",
    "candidate_pool_sha256",
    "corpus_snapshot_sha256",
    "query_id",
    "query_text",
    "query_intent",
    "category",
    "label_order",
    "document_id",
    "content_sha256",
    "name",
    "repository",
    "path",
    "snippet",
    "relevance",
    "rationale",
)


class PoolRecord(BaseModel):
    """Strict immutable base for candidate-pool JSONL records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class CandidatePoolHeader(PoolRecord):
    """Provenance and counts for one reproducible retrieval pool."""

    record_type: Literal["candidate_pool"] = "candidate_pool"
    schema_version: Literal[1] = POOL_SCHEMA_VERSION
    name: str = Field(min_length=1, max_length=100)
    query_set_path: str = Field(min_length=1)
    query_set_sha256: Sha256
    corpus_snapshot_sha256: Sha256
    method: Literal["bm25"] = "bm25"
    pool_depth: int = Field(ge=10, le=100)
    query_count: int = Field(ge=1, le=30)
    item_count: int = Field(ge=1, le=MAX_POOL_ITEMS)
    blinding_version: Literal["sha256-query-document-v1"] = BLINDING_VERSION

    @field_validator("query_set_path")
    @classmethod
    def validate_query_set_path(cls, value: str) -> str:
        _validate_relative_jsonl_path(value)
        return value


class CandidatePoolItem(PoolRecord):
    """One body-free document pooled for one query."""

    record_type: Literal["pool_item"] = "pool_item"
    query_id: QueryId
    document_id: DocumentId
    content_sha256: Sha256
    repository: str = Field(min_length=1, max_length=512)
    path: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=100)
    snippet: str = Field(max_length=2_000)
    validation_status: ValidationStatus
    sources: tuple[Literal["bm25", "query_seed"], ...] = Field(min_length=1, max_length=2)
    bm25_rank: int | None = Field(default=None, ge=1, le=100)

    @field_validator("sources")
    @classmethod
    def validate_sources(
        cls, value: tuple[Literal["bm25", "query_seed"], ...]
    ) -> tuple[Literal["bm25", "query_seed"], ...]:
        expected_order = {"bm25": 0, "query_seed": 1}
        if (
            len(set(value)) != len(value)
            or tuple(sorted(value, key=expected_order.__getitem__)) != value
        ):
            raise ValueError("pool sources must be unique and canonically ordered")
        return value


@dataclass(frozen=True, slots=True)
class CandidatePool:
    """A header plus stable, canonical pooled candidates."""

    header: CandidatePoolHeader
    items: tuple[CandidatePoolItem, ...]


def build_bm25_candidate_pool(
    index: BM25Index,
    query_set: QuerySet,
    *,
    query_set_path: str,
    query_set_sha256: str,
    pool_depth: int,
    name: str = "skillscope-bm25-pool-v1",
) -> CandidatePool:
    """Union BM25 results with authored pool seeds without exposing rank to labels."""

    if not 10 <= pool_depth <= 100:
        raise ValueError("pool_depth must be between 10 and 100")
    if query_set.header.corpus_snapshot_sha256 != index.snapshot_sha256:
        raise StaleCorpusError("query set and BM25 index use different corpus snapshots")
    documents = {document.document_id: document for document in index.documents}

    items: list[CandidatePoolItem] = []
    for query in query_set.queries:
        ranked = index.search(query.query_text, top_k=pool_depth)
        rank_by_document = {
            result.document.document_id: rank for rank, result in enumerate(ranked, start=1)
        }
        candidate_ids = set(rank_by_document) | set(query.pool_seed_document_ids)
        for document_id in sorted(candidate_ids):
            document = documents.get(document_id)
            if document is None:
                raise EvaluationDataError(
                    f"query {query.query_id} pool seed is missing from the frozen corpus: "
                    f"{document_id}"
                )
            sources: list[Literal["bm25", "query_seed"]] = []
            if document_id in rank_by_document:
                sources.append("bm25")
            if document_id in query.pool_seed_document_ids:
                sources.append("query_seed")
            items.append(
                _pool_item(
                    query_id=query.query_id,
                    document=document,
                    sources=tuple(sources),
                    bm25_rank=rank_by_document.get(document_id),
                )
            )

    items.sort(key=lambda item: (item.query_id, item.document_id))
    pool = CandidatePool(
        header=CandidatePoolHeader(
            name=name,
            query_set_path=query_set_path,
            query_set_sha256=query_set_sha256,
            corpus_snapshot_sha256=index.snapshot_sha256,
            pool_depth=pool_depth,
            query_count=len(query_set.queries),
            item_count=len(items),
        ),
        items=tuple(items),
    )
    _validate_candidate_pool(pool)
    return pool


def serialize_candidate_pool(pool: CandidatePool) -> bytes:
    """Return canonical, body-free UTF-8 JSONL for a candidate pool."""

    _validate_candidate_pool(pool)
    records: tuple[PoolRecord, ...] = (pool.header, *pool.items)
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


def write_candidate_pool(path: Path, pool: CandidatePool) -> None:
    """Atomically write a canonical candidate pool."""

    _validate_relative_jsonl_path(path.as_posix())
    _write_atomic(path, serialize_candidate_pool(pool))


def read_candidate_pool(path: Path) -> CandidatePool:
    """Read and strictly validate one canonical candidate pool."""

    serialized = _read_bounded(path, maximum=MAX_POOL_BYTES, label="candidate pool")
    if not serialized.endswith(b"\n"):
        raise EvaluationDataError("candidate pool must end with a newline")
    lines = serialized.splitlines()
    if len(lines) > MAX_POOL_ITEMS + 1 or any(not line or len(line) > 64 * 1024 for line in lines):
        raise EvaluationDataError("candidate pool has an invalid record count or size")
    try:
        pool = CandidatePool(
            header=CandidatePoolHeader.model_validate_json(lines[0]),
            items=tuple(CandidatePoolItem.model_validate_json(line) for line in lines[1:]),
        )
    except (IndexError, ValidationError) as error:
        raise EvaluationDataError("candidate pool contains an invalid record") from error
    _validate_candidate_pool(pool)
    if serialize_candidate_pool(pool) != serialized:
        raise EvaluationDataError("candidate pool is not canonical JSONL")
    return pool


def serialize_label_worksheet(
    pool: CandidatePool,
    query_set: QuerySet,
    *,
    candidate_pool_sha256: str,
) -> bytes:
    """Return a deterministic rank-blinded CSV worksheet with empty labels."""

    rows = _worksheet_rows(
        pool,
        query_set,
        candidate_pool_sha256=candidate_pool_sha256,
    )
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=WORKSHEET_COLUMNS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def write_label_worksheet(
    path: Path,
    pool: CandidatePool,
    query_set: QuerySet,
    *,
    candidate_pool_sha256: str,
) -> None:
    """Atomically write a deterministic rank-blinded CSV worksheet."""

    if path.suffix.lower() != ".csv":
        raise ValueError("labelling worksheet must end with .csv")
    _write_atomic(
        path,
        serialize_label_worksheet(
            pool,
            query_set,
            candidate_pool_sha256=candidate_pool_sha256,
        ),
    )


def qrels_from_label_worksheet(
    path: Path,
    pool: CandidatePool,
    query_set: QuerySet,
    *,
    query_set_path: str,
    candidate_pool_path: str,
    candidate_pool_sha256: str,
    name: str = "skillscope-qrels-v1",
) -> QrelSet:
    """Validate immutable worksheet fields and build canonical graded qrels."""

    serialized = _read_bounded(path, maximum=MAX_WORKSHEET_BYTES, label="label worksheet")
    try:
        decoded = serialized.decode("utf-8")
    except UnicodeDecodeError as error:
        raise EvaluationDataError("label worksheet must be valid UTF-8") from error
    reader = csv.DictReader(io.StringIO(decoded, newline=""))
    if tuple(reader.fieldnames or ()) != WORKSHEET_COLUMNS:
        raise EvaluationDataError("label worksheet columns do not match the frozen template")
    actual_rows = list(reader)
    if any(None in row or set(row) != set(WORKSHEET_COLUMNS) for row in actual_rows):
        raise EvaluationDataError("label worksheet contains unexpected columns or values")
    expected_rows = _worksheet_rows(
        pool,
        query_set,
        candidate_pool_sha256=candidate_pool_sha256,
    )
    if len(actual_rows) != len(expected_rows):
        raise EvaluationDataError("label worksheet row count differs from the candidate pool")

    immutable_columns = WORKSHEET_COLUMNS[:-2]
    judgements: list[QrelRecord] = []
    for actual, expected in zip(actual_rows, expected_rows, strict=True):
        if any(actual[column] != expected[column] for column in immutable_columns):
            raise EvaluationDataError("label worksheet contains modified evidence fields")
        relevance_text = actual["relevance"].strip()
        if relevance_text not in {"0", "1", "2"}:
            raise EvaluationDataError("every worksheet row must have relevance 0, 1, or 2")
        relevance = int(relevance_text)
        rationale = actual["rationale"].strip() or None
        if relevance >= 1 and rationale is None:
            raise EvaluationDataError("relevant worksheet rows require a rationale")
        judgements.append(
            QrelRecord(
                query_id=actual["query_id"],
                document_id=actual["document_id"],
                content_sha256=actual["content_sha256"],
                relevance=relevance,
                rationale=rationale,
            )
        )

    judgements.sort(key=lambda item: (item.query_id, item.document_id))
    return build_qrel_set(
        name=name,
        query_set_path=query_set_path,
        query_set_sha256=pool.header.query_set_sha256,
        candidate_pool_path=candidate_pool_path,
        candidate_pool_sha256=candidate_pool_sha256,
        corpus_snapshot_sha256=pool.header.corpus_snapshot_sha256,
        judgements=tuple(judgements),
    )


def _pool_item(
    *,
    query_id: str,
    document: CorpusDocument,
    sources: tuple[Literal["bm25", "query_seed"], ...],
    bm25_rank: int | None,
) -> CandidatePoolItem:
    return CandidatePoolItem(
        query_id=query_id,
        document_id=document.document_id,
        content_sha256=document.content_sha256,
        repository=document.repository_full_name,
        path=document.path,
        name=document.name,
        snippet=document.safe_snippet,
        validation_status=document.validation_status,
        sources=sources,
        bm25_rank=bm25_rank,
    )


def _validate_candidate_pool(pool: CandidatePool) -> None:
    if pool.header.item_count != len(pool.items):
        raise EvaluationDataError("candidate pool item_count does not match its records")
    keys = [(item.query_id, item.document_id) for item in pool.items]
    if keys != sorted(keys) or len(set(keys)) != len(keys):
        raise EvaluationDataError("candidate pool keys must be unique and ascending")
    query_ids = {item.query_id for item in pool.items}
    if pool.header.query_count != len(query_ids):
        raise EvaluationDataError("candidate pool query_count does not match its records")
    for item in pool.items:
        if ("bm25" in item.sources) != (item.bm25_rank is not None):
            raise EvaluationDataError("BM25 source membership and rank must agree")


def _worksheet_rows(
    pool: CandidatePool,
    query_set: QuerySet,
    *,
    candidate_pool_sha256: str,
) -> list[dict[str, str]]:
    if len(candidate_pool_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in candidate_pool_sha256
    ):
        raise ValueError("candidate_pool_sha256 must be a lowercase SHA-256")
    if pool.header.query_set_sha256 != _query_set_hash(query_set):
        raise EvaluationDataError("candidate pool references different query-set bytes")
    query_by_id = {query.query_id: query for query in query_set.queries}
    items_by_query: dict[str, list[CandidatePoolItem]] = {}
    for item in pool.items:
        items_by_query.setdefault(item.query_id, []).append(item)

    rows: list[dict[str, str]] = []
    for query_id in sorted(items_by_query):
        query = query_by_id.get(query_id)
        if query is None:
            raise EvaluationDataError(f"candidate pool references unknown query: {query_id}")
        blinded = sorted(items_by_query[query_id], key=lambda item: _blind_key(query_id, item))
        for label_order, item in enumerate(blinded, start=1):
            rows.append(
                _worksheet_row(
                    pool=pool,
                    query=query,
                    item=item,
                    label_order=label_order,
                    candidate_pool_sha256=candidate_pool_sha256,
                )
            )
    if set(items_by_query) != set(query_by_id):
        raise EvaluationDataError("candidate pool must contain every frozen query")
    return rows


def _worksheet_row(
    *,
    pool: CandidatePool,
    query: EvaluationQueryRecord,
    item: CandidatePoolItem,
    label_order: int,
    candidate_pool_sha256: str,
) -> dict[str, str]:
    return {
        "schema_version": WORKSHEET_SCHEMA_VERSION,
        "query_set_sha256": pool.header.query_set_sha256,
        "candidate_pool_sha256": candidate_pool_sha256,
        "corpus_snapshot_sha256": pool.header.corpus_snapshot_sha256,
        "query_id": query.query_id,
        "query_text": _csv_safe(query.query_text),
        "query_intent": _csv_safe(query.intent),
        "category": _csv_safe(query.category),
        "label_order": str(label_order),
        "document_id": _csv_safe(item.document_id),
        "content_sha256": item.content_sha256,
        "name": _csv_safe(item.name),
        "repository": _csv_safe(item.repository),
        "path": _csv_safe(item.path),
        "snippet": _csv_safe(item.snippet),
        "relevance": "",
        "rationale": "",
    }


def _blind_key(query_id: str, item: CandidatePoolItem) -> str:
    payload = f"{BLINDING_VERSION}\0{query_id}\0{item.document_id}".encode()
    return hashlib.sha256(payload).hexdigest()


def _csv_safe(value: str) -> str:
    """Keep untrusted metadata inert when the worksheet is opened in a spreadsheet."""

    stripped = value.lstrip(" \t\r\n")
    if stripped.startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return f"'{value}"
    return value


def _query_set_hash(query_set: QuerySet) -> str:
    from skillscope.evaluation.data import serialize_query_set

    return hashlib.sha256(serialize_query_set(query_set)).hexdigest()


def _read_bounded(path: Path, *, maximum: int, label: str) -> bytes:
    try:
        serialized = path.read_bytes()
    except OSError as error:
        raise EvaluationDataError(f"{label} could not be read: {path}") from error
    if not serialized or len(serialized) > maximum:
        raise EvaluationDataError(f"{label} is empty or exceeds its safety limit")
    return serialized


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


def _validate_relative_jsonl_path(value: str) -> None:
    path = Path(value)
    if (
        path.is_absolute()
        or path.suffix != ".jsonl"
        or ".." in path.parts
        or not value
        or value.startswith("./")
        or path.as_posix() != value
    ):
        raise ValueError("candidate-pool paths must be normalized safe relative JSONL paths")
