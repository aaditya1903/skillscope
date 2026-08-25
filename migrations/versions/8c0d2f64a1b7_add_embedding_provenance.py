"""add embedding provenance

Revision ID: 8c0d2f64a1b7
Revises: ddfda2ba04bd
Create Date: 2026-08-25 12:00:00+00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8c0d2f64a1b7"
down_revision: str | Sequence[str] | None = "ddfda2ba04bd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add complete model, configuration, content, and text provenance."""

    op.add_column("skills", sa.Column("embedding_model_id", sa.String(255), nullable=True))
    op.add_column(
        "skills",
        sa.Column("embedding_model_revision", sa.String(40), nullable=True),
    )
    op.add_column(
        "skills",
        sa.Column("embedding_config_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "skills",
        sa.Column("embedding_content_sha256", sa.String(64), nullable=True),
    )
    op.add_column(
        "skills",
        sa.Column("embedding_text_sha256", sa.String(64), nullable=True),
    )
    # Embeddings are derived and older rows cannot prove which model or text
    # produced them. Clear any such vectors before enforcing provenance.
    op.execute("UPDATE skills SET embedding = NULL, indexed_at = NULL")
    op.create_check_constraint(
        op.f("ck_skills_embedding_provenance_complete"),
        "skills",
        "(embedding IS NULL AND embedding_model_id IS NULL "
        "AND embedding_model_revision IS NULL AND embedding_config_sha256 IS NULL "
        "AND embedding_content_sha256 IS NULL AND embedding_text_sha256 IS NULL "
        "AND indexed_at IS NULL) OR "
        "(embedding IS NOT NULL AND embedding_model_id IS NOT NULL "
        "AND embedding_model_revision IS NOT NULL AND embedding_config_sha256 IS NOT NULL "
        "AND embedding_content_sha256 IS NOT NULL AND embedding_text_sha256 IS NOT NULL "
        "AND indexed_at IS NOT NULL)",
    )
    op.create_check_constraint(
        op.f("ck_skills_embedding_provenance_hash_lengths"),
        "skills",
        "(embedding_model_revision IS NULL OR char_length(embedding_model_revision) = 40) "
        "AND (embedding_config_sha256 IS NULL "
        "OR char_length(embedding_config_sha256) = 64) "
        "AND (embedding_content_sha256 IS NULL "
        "OR char_length(embedding_content_sha256) = 64) "
        "AND (embedding_text_sha256 IS NULL "
        "OR char_length(embedding_text_sha256) = 64)",
    )


def downgrade() -> None:
    """Remove provenance and invalidate the derived vectors it governed."""

    op.drop_constraint(
        op.f("ck_skills_embedding_provenance_hash_lengths"),
        "skills",
        type_="check",
    )
    op.drop_constraint(
        op.f("ck_skills_embedding_provenance_complete"),
        "skills",
        type_="check",
    )
    op.execute("UPDATE skills SET embedding = NULL, indexed_at = NULL")
    op.drop_column("skills", "embedding_text_sha256")
    op.drop_column("skills", "embedding_content_sha256")
    op.drop_column("skills", "embedding_config_sha256")
    op.drop_column("skills", "embedding_model_revision")
    op.drop_column("skills", "embedding_model_id")
