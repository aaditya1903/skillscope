"""Exact PostgreSQL pgvector dense retrieval over the frozen corpus."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from skillscope.db.models import Repository, Skill
from skillscope.retrieval.config import DenseHybridConfig
from skillscope.retrieval.corpus import CorpusDocument, FrozenCorpus, StaleCorpusError
from skillscope.retrieval.embeddings import (
    EmbeddingContractError,
    EmbeddingEncoder,
    validate_embedding_matrix,
)
from skillscope.retrieval.filters import RetrievalFilters


class EmbeddingCoverageError(ValueError):
    """The frozen corpus is missing current, contract-compliant embeddings."""


@dataclass(frozen=True, slots=True)
class DenseResult:
    """One exact cosine-ranked document with interpretable score evidence."""

    document: CorpusDocument
    cosine_distance: float
    cosine_similarity: float


class DenseRetriever:
    """Embed queries and execute exact cosine ordering in PostgreSQL."""

    def __init__(
        self,
        session: Session,
        corpus: FrozenCorpus,
        config: DenseHybridConfig,
        encoder: EmbeddingEncoder,
        *,
        embedding_config_sha256: str,
    ) -> None:
        if corpus.snapshot_sha256 != config.corpus_snapshot_sha256:
            raise StaleCorpusError("dense retriever and configuration use different snapshots")
        if (
            encoder.model_id != config.model_id
            or encoder.model_revision != config.model_revision
            or encoder.dimension != config.model_dimension
        ):
            raise EmbeddingContractError(
                "dense query encoder differs from the pinned configuration"
            )
        self.session = session
        self.corpus = corpus
        self.config = config
        self.encoder = encoder
        self.embedding_config_sha256 = embedding_config_sha256
        self._documents_by_skill_id = {document.skill_id: document for document in corpus.documents}
        self._validate_embedding_coverage()

    def search(
        self,
        query: str,
        *,
        top_k: int | None = None,
        filters: RetrievalFilters | None = None,
    ) -> tuple[DenseResult, ...]:
        """Return exact nearest neighbours after applying shared filters."""

        result_limit = top_k if top_k is not None else self.config.default_top_k
        if not 1 <= result_limit <= 100:
            raise ValueError("top_k must be between 1 and 100")
        if not query.strip():
            return ()

        eligible_documents = tuple(
            document
            for document in self.corpus.documents
            if filters is None or filters.allows(document)
        )
        if not eligible_documents:
            return ()

        query_embeddings = self.encoder.encode((query,), batch_size=1)
        validate_embedding_matrix(
            query_embeddings,
            expected_rows=1,
            dimension=self.config.model_dimension,
            require_unit_norm=self.config.normalize_embeddings,
        )
        query_vector = [float(value) for value in query_embeddings[0]]
        distance = Skill.embedding.cosine_distance(query_vector).label("cosine_distance")
        eligible_skill_ids = tuple(document.skill_id for document in eligible_documents)
        statement = (
            select(Skill.id, distance)
            .join(Repository, Skill.repository_id == Repository.id)
            .where(
                Skill.id.in_(eligible_skill_ids),
                Skill.embedding.is_not(None),
                Skill.embedding_model_id == self.config.model_id,
                Skill.embedding_model_revision == self.config.model_revision,
                Skill.embedding_config_sha256 == self.embedding_config_sha256,
            )
            .order_by(
                distance.asc(),
                func.lower(Repository.full_name).asc(),
                func.lower(Skill.path).asc(),
                Skill.id.asc(),
            )
            .limit(result_limit)
        )
        rows = self.session.execute(statement).tuples().all()
        results: list[DenseResult] = []
        for skill_id, raw_distance in rows:
            if raw_distance is None:
                raise EmbeddingCoverageError("pgvector returned a null cosine distance")
            cosine_distance = float(raw_distance)
            cosine_similarity = max(-1.0, min(1.0, 1.0 - cosine_distance))
            results.append(
                DenseResult(
                    document=self._documents_by_skill_id[skill_id],
                    cosine_distance=cosine_distance,
                    cosine_similarity=cosine_similarity,
                )
            )
        return tuple(results)

    def _validate_embedding_coverage(self) -> None:
        rows = self.session.execute(
            select(
                Skill.id,
                Skill.embedding,
                Skill.embedding_model_id,
                Skill.embedding_model_revision,
                Skill.embedding_config_sha256,
                Skill.embedding_content_sha256,
                Skill.embedding_text_sha256,
                Skill.indexed_at,
            ).where(Skill.id.in_(self._documents_by_skill_id))
        ).tuples()
        rows_by_id = {row[0]: row for row in rows}
        for skill_id, document in self._documents_by_skill_id.items():
            row = rows_by_id.get(skill_id)
            if row is None:
                raise EmbeddingCoverageError(
                    f"frozen document is missing from the database: {document.document_id}"
                )
            (
                _,
                embedding,
                model_id,
                model_revision,
                config_sha256,
                content_sha256,
                text_sha256,
                indexed_at,
            ) = row
            if (
                embedding is None
                or model_id != self.config.model_id
                or model_revision != self.config.model_revision
                or config_sha256 != self.embedding_config_sha256
                or content_sha256 != document.content_sha256
                or text_sha256 != document.embedding_text_sha256
                or indexed_at is None
            ):
                raise EmbeddingCoverageError(
                    f"embedding is missing or stale for document: {document.document_id}"
                )
            vector = np.asarray(embedding, dtype=np.float32).reshape(1, -1)
            try:
                validate_embedding_matrix(
                    vector,
                    expected_rows=1,
                    dimension=self.config.model_dimension,
                    require_unit_norm=self.config.normalize_embeddings,
                )
            except EmbeddingContractError as error:
                raise EmbeddingCoverageError(
                    f"stored embedding is invalid for document: {document.document_id}"
                ) from error
