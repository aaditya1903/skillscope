"""Schema-shape tests that do not require a running database."""

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import UniqueConstraint

from skillscope.db import models as db_models
from skillscope.db.base import Base
from skillscope.db.enums import LicenseStatus, RetrievalMethod, ValidationStatus

REQUIRED_TABLES = {
    "repositories",
    "skills",
    "skill_files",
    "ingestion_runs",
    "ingestion_run_items",
    "evaluation_queries",
    "qrels",
    "evaluation_runs",
}


def test_required_tables_are_registered() -> None:
    assert REQUIRED_TABLES <= set(Base.metadata.tables)


def test_skill_embedding_dimension_and_deferred_body() -> None:
    embedding_type = db_models.Skill.__table__.c.embedding.type

    assert isinstance(embedding_type, VECTOR)
    assert embedding_type.dim == 384
    assert db_models.Skill.__mapper__.column_attrs["body_text"].deferred is True


def test_idempotency_constraints_are_declared() -> None:
    skill_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in db_models.Skill.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    qrel_unique_columns = {
        tuple(column.name for column in constraint.columns)
        for constraint in db_models.Qrel.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert ("repository_id", "path") in skill_unique_columns
    assert ("query_id", "skill_id") in qrel_unique_columns


def test_public_enum_values_are_stable() -> None:
    assert [status.value for status in LicenseStatus] == [
        "permissive",
        "restrictive",
        "missing",
        "unknown",
    ]
    assert [status.value for status in ValidationStatus] == [
        "valid",
        "warning",
        "invalid",
    ]
    assert [method.value for method in RetrievalMethod] == ["bm25", "dense", "hybrid"]
