"""PostgreSQL and pgvector integration coverage for the persistence layer."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from psycopg.errors import ForeignKeyViolation, UniqueViolation
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from skillscope.db import session as db_session_module
from skillscope.db.enums import LicenseStatus, ValidationStatus
from skillscope.db.models import Repository, Skill

pytestmark = pytest.mark.integration

PROJECT_ROOT = Path(__file__).resolve().parents[2]
EMBEDDING_DIMENSION = 384


def _repository(
    *,
    github_repository_id: int = 101,
    full_name: str = "skillscope-tests/catalogue",
) -> Repository:
    """Build deterministic synthetic repository metadata."""

    owner, name = full_name.split("/", maxsplit=1)
    return Repository(
        github_repository_id=github_repository_id,
        owner=owner,
        name=name,
        full_name=full_name,
        html_url=f"https://github.com/{full_name}",
        default_branch="main",
        description="Synthetic integration-test repository.",
        license_spdx_id="MIT",
        license_name="MIT License",
        license_status=LicenseStatus.PERMISSIVE,
        pushed_at=None,
        etag='"integration-fixture"',
    )


def _skill(
    repository: Repository | None = None,
    *,
    repository_id: UUID | None = None,
    path: str = "skills/catalogue/SKILL.md",
    name: str = "catalogue",
    embedding: list[float] | None = None,
) -> Skill:
    """Build a synthetic skill without relying on third-party content."""

    has_embedding = embedding is not None
    skill = Skill(
        path=path,
        html_url=f"https://github.com/skillscope-tests/catalogue/blob/main/{path}",
        raw_url=None,
        git_blob_sha="a" * 40,
        content_sha256="b" * 64,
        name=name,
        description="Synthetic skill used only for database integration tests.",
        declared_license="MIT",
        compatibility=None,
        allowed_tools=["Read"],
        metadata_json={"fixture": "true"},
        extension_fields_json={},
        body_text="# Synthetic skill\n\nThis text is inert test data.",
        search_text="synthetic database integration skill",
        safe_snippet="Synthetic skill used for database integration tests.",
        embedding=embedding,
        embedding_model_id=("sentence-transformers/all-MiniLM-L6-v2" if has_embedding else None),
        embedding_model_revision="a" * 40 if has_embedding else None,
        embedding_config_sha256="c" * 64 if has_embedding else None,
        embedding_content_sha256="b" * 64 if has_embedding else None,
        embedding_text_sha256="d" * 64 if has_embedding else None,
        validation_status=ValidationStatus.VALID,
        validation_messages_json=[],
        indexed_at=datetime(2030, 1, 1, tzinfo=UTC) if has_embedding else None,
    )

    if repository is not None:
        skill.repository = repository
    elif repository_id is not None:
        skill.repository_id = repository_id
    else:
        raise ValueError("repository or repository_id is required")

    return skill


def test_database_is_migrated_to_head(migrated_engine: Engine) -> None:
    alembic_config = Config(str(PROJECT_ROOT / "alembic.ini"))
    expected_head = ScriptDirectory.from_config(alembic_config).get_current_head()

    with migrated_engine.connect() as connection:
        current_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        vector_version = connection.scalar(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        )

    assert expected_head is not None
    assert current_revision == expected_head
    assert vector_version is not None


def test_repository_skill_and_vectors_round_trip(db_session: Session) -> None:
    repository = _repository()
    x_axis = [1.0] + [0.0] * (EMBEDDING_DIMENSION - 1)
    y_axis = [0.0, 1.0] + [0.0] * (EMBEDDING_DIMENSION - 2)
    query_vector = [0.9, 0.1] + [0.0] * (EMBEDDING_DIMENSION - 2)
    nearest = _skill(repository, name="nearest", embedding=x_axis)
    farther = _skill(
        repository,
        path="skills/farther/SKILL.md",
        name="farther",
        embedding=y_axis,
    )
    db_session.add_all([repository, nearest, farther])
    db_session.flush()

    ranked_ids = db_session.scalars(
        select(Skill.id)
        .where(Skill.repository_id == repository.id)
        .order_by(Skill.embedding.cosine_distance(query_vector))
        .limit(2)
    ).all()
    stored_embedding = db_session.scalar(select(Skill.embedding).where(Skill.id == nearest.id))

    assert ranked_ids == [nearest.id, farther.id]
    assert stored_embedding is not None
    assert len(stored_embedding) == EMBEDDING_DIMENSION


@pytest.mark.parametrize(
    ("duplicate_field", "expected_constraint"),
    [
        ("github_repository_id", "uq_repositories_github_repository_id"),
        ("full_name", "uq_repositories_full_name"),
    ],
)
def test_repository_unique_constraints_reject_duplicates(
    db_session: Session,
    duplicate_field: str,
    expected_constraint: str,
) -> None:
    first = _repository()
    if duplicate_field == "github_repository_id":
        duplicate = _repository(
            github_repository_id=first.github_repository_id,
            full_name="skillscope-tests/other",
        )
    else:
        duplicate = _repository(
            github_repository_id=102,
            full_name=first.full_name,
        )

    db_session.add(first)
    db_session.flush()
    db_session.add(duplicate)

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    database_error = exc_info.value.orig
    assert isinstance(database_error, UniqueViolation)
    assert database_error.diag.constraint_name == expected_constraint
    db_session.rollback()


def test_skill_path_unique_constraint_rejects_duplicate(
    db_session: Session,
) -> None:
    repository = _repository()
    db_session.add_all(
        [
            repository,
            _skill(repository),
            _skill(repository, name="duplicate-catalogue"),
        ]
    )

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    database_error = exc_info.value.orig
    assert isinstance(database_error, UniqueViolation)
    assert database_error.diag.constraint_name == "uq_skills_repository_id_path"
    db_session.rollback()


def test_skill_foreign_key_rejects_unknown_repository(
    db_session: Session,
) -> None:
    db_session.add(_skill(repository_id=uuid4()))

    with pytest.raises(IntegrityError) as exc_info:
        db_session.flush()

    database_error = exc_info.value.orig
    assert isinstance(database_error, ForeignKeyViolation)
    assert database_error.diag.constraint_name == "fk_skills_repository_id_repositories"
    db_session.rollback()


def test_session_scope_rolls_back_failed_unit_of_work(
    migrated_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unique_suffix = uuid4().hex
    github_repository_id = uuid4().int % (2**63 - 1)
    full_name = f"skillscope-tests/rollback-{unique_suffix}"
    factory = sessionmaker(bind=migrated_engine, expire_on_commit=False)
    monkeypatch.setattr(
        db_session_module,
        "get_session_factory",
        lambda: factory,
    )

    with pytest.raises(RuntimeError, match="rollback integration probe"):
        with db_session_module.session_scope() as session:
            session.add(
                _repository(
                    github_repository_id=github_repository_id,
                    full_name=full_name,
                )
            )
            session.flush()
            raise RuntimeError("rollback integration probe")

    with factory() as verification_session:
        stored_repository = verification_session.scalar(
            select(Repository).where(Repository.full_name == full_name)
        )

    assert stored_repository is None
