"""PostgreSQL-backed embedding indexing and exact cosine retrieval tests."""

from datetime import UTC, datetime

import numpy as np
import pytest
from sqlalchemy.orm import Session

from skillscope.db.enums import LicenseStatus, ValidationStatus
from skillscope.db.models import Repository, Skill
from skillscope.retrieval.config import DenseHybridConfig
from skillscope.retrieval.corpus import CorpusDocument, FrozenCorpus, LexicalFields
from skillscope.retrieval.dense import DenseRetriever, EmbeddingCoverageError
from skillscope.retrieval.embeddings import index_frozen_corpus_embeddings
from skillscope.retrieval.filters import RetrievalFilters

pytestmark = pytest.mark.integration
SNAPSHOT_SHA = "a" * 64
CONFIG_SHA = "b" * 64


class DeterministicEncoder:
    """Map synthetic alpha/beta text onto orthogonal normalized vectors."""

    model_id: str = "sentence-transformers/all-MiniLM-L6-v2"
    model_revision: str = "1" * 40
    dimension: int = 384

    def __init__(self) -> None:
        self.batch_count = 0

    def encode(self, texts: tuple[str, ...], *, batch_size: int) -> np.ndarray:
        self.batch_count += 1
        matrix = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for index, text in enumerate(texts):
            matrix[index, 0 if "alpha" in text.casefold() else 1] = 1.0
        return matrix


def _config() -> DenseHybridConfig:
    return DenseHybridConfig(
        model_id="sentence-transformers/all-MiniLM-L6-v2",
        model_revision="1" * 40,
        sentence_transformers_version="6.0.0",
        batch_size=1,
        default_top_k=10,
        bm25_weight=1.0,
        dense_weight=1.0,
        corpus_snapshot_path="data/manifests/test.jsonl",
        corpus_snapshot_sha256=SNAPSHOT_SHA,
        bm25_config_path="config/retrieval/bm25.json",
        bm25_config_sha256="c" * 64,
        eligible_validation_statuses=("valid", "warning"),
    )


def _skill(repository: Repository, number: int, name: str, *, has_scripts: bool) -> Skill:
    return Skill(
        repository=repository,
        path=f"skills/{name}/SKILL.md",
        html_url=f"https://github.com/example/catalogue/blob/main/skills/{name}/SKILL.md",
        raw_url=None,
        git_blob_sha=f"{number}" * 40,
        content_sha256=f"{number}" * 64,
        name=name,
        description=f"Synthetic {name} retrieval skill.",
        declared_license="MIT",
        compatibility=None,
        allowed_tools=[],
        metadata_json={},
        extension_fields_json={},
        body_text=f"# {name}\nUse the {name} workflow.",
        search_text=f"{name} workflow",
        safe_snippet=f"Synthetic {name} retrieval skill.",
        embedding=None,
        validation_status=ValidationStatus.VALID,
        validation_messages_json=[],
        has_scripts=has_scripts,
        indexed_at=None,
    )


def _document(skill: Skill, repository: Repository) -> CorpusDocument:
    return CorpusDocument(
        document_id=f"github:{repository.github_repository_id}:{skill.path}",
        skill_id=skill.id,
        repository_id=repository.github_repository_id,
        repository_full_name=repository.full_name,
        path=skill.path,
        name=skill.name,
        safe_snippet=skill.safe_snippet,
        validation_status=skill.validation_status,
        content_sha256=skill.content_sha256,
        fields=LexicalFields(skill.name, skill.description, "mit", skill.name, skill.search_text),
        tokens=(skill.name,),
        license_status=repository.license_status,
        has_scripts=skill.has_scripts,
    )


def _prepare(db_session: Session) -> tuple[FrozenCorpus, DeterministicEncoder, Skill, Skill]:
    repository = Repository(
        github_repository_id=98_765,
        owner="example",
        name="catalogue",
        full_name="example/catalogue",
        html_url="https://github.com/example/catalogue",
        default_branch="main",
        description="Synthetic dense retrieval fixture.",
        license_spdx_id="MIT",
        license_name="MIT License",
        license_status=LicenseStatus.PERMISSIVE,
        pushed_at=None,
        etag='"dense"',
    )
    alpha = _skill(repository, 1, "alpha", has_scripts=True)
    beta = _skill(repository, 2, "beta", has_scripts=False)
    db_session.add_all([repository, alpha, beta])
    db_session.flush()
    corpus = FrozenCorpus(
        snapshot_path="data/manifests/test.jsonl",
        snapshot_sha256=SNAPSHOT_SHA,
        documents=(_document(alpha, repository), _document(beta, repository)),
    )
    return corpus, DeterministicEncoder(), alpha, beta


def test_indexer_batches_and_identical_second_run_is_unchanged(db_session: Session) -> None:
    corpus, encoder, alpha, beta = _prepare(db_session)

    first = index_frozen_corpus_embeddings(
        db_session,
        corpus,
        _config(),
        encoder,
        embedding_config_sha256=CONFIG_SHA,
        indexed_at=datetime(2030, 1, 1, tzinfo=UTC),
    )
    second = index_frozen_corpus_embeddings(
        db_session,
        corpus,
        _config(),
        encoder,
        embedding_config_sha256=CONFIG_SHA,
        indexed_at=datetime(2030, 1, 2, tzinfo=UTC),
    )

    assert (first.indexed_count, first.unchanged_count) == (2, 0)
    assert (second.indexed_count, second.unchanged_count) == (0, 2)
    assert encoder.batch_count == 2
    assert alpha.embedding_content_sha256 == alpha.content_sha256
    assert beta.embedding_model_revision == "1" * 40
    assert alpha.indexed_at == datetime(2030, 1, 1, tzinfo=UTC)


def test_exact_cosine_search_and_filters_use_the_same_frozen_documents(
    db_session: Session,
) -> None:
    corpus, encoder, alpha, _ = _prepare(db_session)
    index_frozen_corpus_embeddings(
        db_session,
        corpus,
        _config(),
        encoder,
        embedding_config_sha256=CONFIG_SHA,
    )
    retriever = DenseRetriever(
        db_session,
        corpus,
        _config(),
        encoder,
        embedding_config_sha256=CONFIG_SHA,
    )

    results = retriever.search("alpha request", top_k=2)
    filtered = retriever.search(
        "beta request",
        top_k=2,
        filters=RetrievalFilters(has_scripts=True),
    )

    assert [result.document.skill_id for result in results] == [
        alpha.id,
        next(document.skill_id for document in corpus.documents if document.skill_id != alpha.id),
    ]
    assert results[0].cosine_similarity == pytest.approx(1.0)
    assert [result.document.skill_id for result in filtered] == [alpha.id]


def test_dense_retriever_rejects_content_hash_or_vector_drift(db_session: Session) -> None:
    corpus, encoder, alpha, _ = _prepare(db_session)
    index_frozen_corpus_embeddings(
        db_session,
        corpus,
        _config(),
        encoder,
        embedding_config_sha256=CONFIG_SHA,
    )
    alpha.embedding_content_sha256 = "f" * 64
    db_session.flush()

    with pytest.raises(EmbeddingCoverageError, match="missing or stale"):
        DenseRetriever(
            db_session,
            corpus,
            _config(),
            encoder,
            embedding_config_sha256=CONFIG_SHA,
        )
