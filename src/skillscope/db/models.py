"""Normalized SQLAlchemy models for ingestion, retrieval, and evaluation."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pgvector.sqlalchemy import VECTOR
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from skillscope.db.base import Base, UUIDPrimaryKeyMixin
from skillscope.db.enums import (
    EvaluationSplit,
    IngestionItemStatus,
    IngestionRunStatus,
    LicenseStatus,
    RetrievalMethod,
    SupportingFileType,
    ValidationStatus,
)


def _enum_check_constraint(
    column_name: str,
    enum_class: type[StrEnum],
    *,
    name: str,
) -> CheckConstraint:
    """Expose enum checks as named metadata constraints for Alembic."""

    escaped_values = (member.value.replace("'", "''") for member in enum_class)
    values_sql = ", ".join(f"'{value}'" for value in escaped_values)
    return CheckConstraint(f"{column_name} IN ({values_sql})", name=name)


class Repository(UUIDPrimaryKeyMixin, Base):
    """A public GitHub repository containing one or more Agent Skills."""

    __tablename__ = "repositories"
    __table_args__ = (
        UniqueConstraint("github_repository_id"),
        UniqueConstraint("full_name"),
        CheckConstraint(
            "stars_count >= 0 AND forks_count >= 0 AND open_issues_count >= 0",
            name="counts_nonnegative",
        ),
        _enum_check_constraint(
            "license_status",
            LicenseStatus,
            name="license_status",
        ),
    )

    github_repository_id: Mapped[int] = mapped_column(BigInteger)
    owner: Mapped[str] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(512))
    html_url: Mapped[str] = mapped_column(Text)
    default_branch: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    stars_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    forks_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    open_issues_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_fork: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    license_spdx_id: Mapped[str | None] = mapped_column(String(255))
    license_name: Mapped[str | None] = mapped_column(String(255))
    license_status: Mapped[LicenseStatus] = mapped_column(
        SAEnum(
            LicenseStatus,
            name="license_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda enum_class: [member.value for member in enum_class],
        )
    )
    pushed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    etag: Mapped[str | None] = mapped_column(String(255))

    skills: Mapped[list[Skill]] = relationship(
        back_populates="repository",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Skill(UUIDPrimaryKeyMixin, Base):
    """A parsed SKILL.md plus safe, derived retrieval metadata."""

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("repository_id", "path"),
        CheckConstraint("char_length(content_sha256) = 64", name="content_sha256_length"),
        CheckConstraint(
            "script_count >= 0 AND reference_count >= 0 AND asset_count >= 0 "
            "AND heading_count >= 0 AND code_block_count >= 0 "
            "AND external_link_count >= 0 AND word_count >= 0 AND byte_count >= 0",
            name="counts_nonnegative",
        ),
        _enum_check_constraint(
            "validation_status",
            ValidationStatus,
            name="validation_status",
        ),
    )

    repository_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("repositories.id", ondelete="CASCADE"),
    )
    path: Mapped[str] = mapped_column(Text)
    html_url: Mapped[str] = mapped_column(Text)
    raw_url: Mapped[str | None] = mapped_column(Text)
    git_blob_sha: Mapped[str] = mapped_column(String(64))
    content_sha256: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(1024))
    declared_license: Mapped[str | None] = mapped_column(String(255))
    compatibility: Mapped[str | None] = mapped_column(Text)
    allowed_tools: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    extension_fields_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    body_text: Mapped[str] = mapped_column(Text, deferred=True)
    search_text: Mapped[str] = mapped_column(Text)
    safe_snippet: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float] | None] = mapped_column(VECTOR(384))
    validation_status: Mapped[ValidationStatus] = mapped_column(
        SAEnum(
            ValidationStatus,
            name="validation_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda enum_class: [member.value for member in enum_class],
        )
    )
    validation_messages_json: Mapped[list[object]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    has_scripts: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    has_references: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    has_assets: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    script_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    reference_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    asset_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    heading_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    code_block_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    external_link_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    word_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    byte_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    repository: Mapped[Repository] = relationship(back_populates="skills")
    files: Mapped[list[SkillFile]] = relationship(
        back_populates="skill",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    qrels: Mapped[list[Qrel]] = relationship(
        back_populates="skill",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class SkillFile(UUIDPrimaryKeyMixin, Base):
    """Structural metadata for a supporting file, never its contents."""

    __tablename__ = "skill_files"
    __table_args__ = (
        UniqueConstraint("skill_id", "relative_path"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_nonnegative"),
        _enum_check_constraint(
            "file_type",
            SupportingFileType,
            name="supporting_file_type",
        ),
    )

    skill_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
    )
    relative_path: Mapped[str] = mapped_column(Text)
    file_type: Mapped[SupportingFileType] = mapped_column(
        SAEnum(
            SupportingFileType,
            name="supporting_file_type",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda enum_class: [member.value for member in enum_class],
        )
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    git_blob_sha: Mapped[str] = mapped_column(String(64))
    extension: Mapped[str | None] = mapped_column(String(32))

    skill: Mapped[Skill] = relationship(back_populates="files")


class IngestionRun(UUIDPrimaryKeyMixin, Base):
    """One reproducible execution of candidate discovery and ingestion."""

    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "discovered_count >= 0 AND fetched_count >= 0 AND unchanged_count >= 0 "
            "AND parsed_count >= 0 AND invalid_count >= 0 AND error_count >= 0",
            name="counts_nonnegative",
        ),
        _enum_check_constraint(
            "status",
            IngestionRunStatus,
            name="ingestion_run_status",
        ),
    )

    status: Mapped[IngestionRunStatus] = mapped_column(
        SAEnum(
            IngestionRunStatus,
            name="ingestion_run_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda enum_class: [member.value for member in enum_class],
        ),
        default=IngestionRunStatus.RUNNING,
        server_default=IngestionRunStatus.RUNNING.value,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    discovery_queries_json: Mapped[list[str]] = mapped_column(
        JSONB, default=list, server_default=text("'[]'::jsonb")
    )
    config_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    git_commit_sha: Mapped[str] = mapped_column(String(64))
    discovered_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    fetched_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    unchanged_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    parsed_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    invalid_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    rate_limit_start_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    rate_limit_end_json: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    manifest_path: Mapped[str | None] = mapped_column(Text)

    items: Mapped[list[IngestionRunItem]] = relationship(
        back_populates="ingestion_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class IngestionRunItem(UUIDPrimaryKeyMixin, Base):
    """Outcome for one candidate considered by an ingestion run."""

    __tablename__ = "ingestion_run_items"
    __table_args__ = (
        UniqueConstraint("ingestion_run_id", "repository_full_name", "path"),
        CheckConstraint(
            "content_sha256 IS NULL OR char_length(content_sha256) = 64",
            name="content_sha256_length",
        ),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="duration_ms_nonnegative",
        ),
        _enum_check_constraint(
            "status",
            IngestionItemStatus,
            name="ingestion_item_status",
        ),
    )

    ingestion_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ingestion_runs.id", ondelete="CASCADE"),
    )
    repository_full_name: Mapped[str] = mapped_column(String(512))
    path: Mapped[str] = mapped_column(Text)
    status: Mapped[IngestionItemStatus] = mapped_column(
        SAEnum(
            IngestionItemStatus,
            name="ingestion_item_status",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda enum_class: [member.value for member in enum_class],
        )
    )
    reason: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    ingestion_run: Mapped[IngestionRun] = relationship(back_populates="items")


class EvaluationQuery(UUIDPrimaryKeyMixin, Base):
    """A manually authored retrieval-evaluation query."""

    __tablename__ = "evaluation_queries"
    __table_args__ = (
        CheckConstraint("char_length(btrim(query_text)) > 0", name="query_text_nonempty"),
        _enum_check_constraint(
            "split",
            EvaluationSplit,
            name="evaluation_split",
        ),
    )

    query_text: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(100))
    split: Mapped[EvaluationSplit] = mapped_column(
        SAEnum(
            EvaluationSplit,
            name="evaluation_split",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda enum_class: [member.value for member in enum_class],
        )
    )
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    qrels: Mapped[list[Qrel]] = relationship(
        back_populates="query",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class Qrel(UUIDPrimaryKeyMixin, Base):
    """A graded relevance judgement for one query-skill pair."""

    __tablename__ = "qrels"
    __table_args__ = (
        UniqueConstraint("query_id", "skill_id"),
        CheckConstraint("relevance BETWEEN 0 AND 2", name="relevance_range"),
    )

    query_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("evaluation_queries.id", ondelete="CASCADE"),
    )
    skill_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("skills.id", ondelete="CASCADE"),
    )
    relevance: Mapped[int] = mapped_column(SmallInteger)
    rationale: Mapped[str | None] = mapped_column(Text)
    labelled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    query: Mapped[EvaluationQuery] = relationship(back_populates="qrels")
    skill: Mapped[Skill] = relationship(back_populates="qrels")


class EvaluationRun(UUIDPrimaryKeyMixin, Base):
    """Metrics and latency evidence for one retrieval method and snapshot."""

    __tablename__ = "evaluation_runs"
    __table_args__ = (
        _enum_check_constraint(
            "method",
            RetrievalMethod,
            name="retrieval_method",
        ),
    )

    name: Mapped[str] = mapped_column(String(255))
    dataset_snapshot_sha: Mapped[str] = mapped_column(String(71))
    git_commit_sha: Mapped[str] = mapped_column(String(64))
    method: Mapped[RetrievalMethod] = mapped_column(
        SAEnum(
            RetrievalMethod,
            name="retrieval_method",
            native_enum=False,
            create_constraint=False,
            validate_strings=True,
            values_callable=lambda enum_class: [member.value for member in enum_class],
        )
    )
    config_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    metrics_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    latency_json: Mapped[dict[str, object]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    report_path: Mapped[str | None] = mapped_column(Text)
