"""Schema-shape tests that do not require a running database."""

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy import Enum as SAEnum

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
    assert {
        "embedding_model_id",
        "embedding_model_revision",
        "embedding_config_sha256",
        "embedding_content_sha256",
        "embedding_text_sha256",
    } <= set(db_models.Skill.__table__.columns.keys())
    constraint_names = {
        constraint.name
        for constraint in db_models.Skill.__table__.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert "ck_skills_embedding_provenance_complete" in constraint_names
    assert "ck_skills_embedding_provenance_hash_lengths" in constraint_names


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


def test_enum_columns_use_explicit_named_check_constraints() -> None:
    expected_names = {
        "ck_evaluation_queries_evaluation_split",
        "ck_evaluation_runs_retrieval_method",
        "ck_ingestion_run_items_ingestion_item_status",
        "ck_ingestion_runs_ingestion_run_status",
        "ck_repositories_license_status",
        "ck_skill_files_supporting_file_type",
        "ck_skills_validation_status",
    }
    actual_names = {
        constraint.name
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    enum_types = [
        column.type
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, SAEnum)
    ]

    assert len(enum_types) == 7
    assert all(enum_type.create_constraint is False for enum_type in enum_types)
    assert expected_names <= actual_names
