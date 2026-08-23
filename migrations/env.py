"""Alembic environment configured from SkillScope application settings."""

from logging.config import fileConfig

from alembic import context
from alembic.autogenerate.api import AutogenContext
from pgvector.sqlalchemy import VECTOR
from sqlalchemy import engine_from_config, pool

from skillscope.core.config import get_settings
from skillscope.db import models

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = models.Base.metadata


def render_item(type_: str, obj: object, autogen_context: AutogenContext) -> str | bool:
    """Render pgvector columns with an explicit, runnable import."""

    if type_ == "type" and isinstance(obj, VECTOR):
        autogen_context.imports.add("from pgvector.sqlalchemy import VECTOR")
        return f"VECTOR({obj.dim})" if obj.dim is not None else "VECTOR()"

    return False


def database_url() -> str:
    """Read the database URL without storing credentials in alembic.ini."""

    return str(get_settings().database_url)


def run_migrations_offline() -> None:
    """Render migration SQL without opening a database connection."""

    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_item=render_item,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against the configured PostgreSQL database."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_item=render_item,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
