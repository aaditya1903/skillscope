"""Fixtures for integration tests against an isolated PostgreSQL database."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from skillscope.core.config import get_settings
from skillscope.db.base import Base

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL_ENV = "SKILLSCOPE_TEST_DATABASE_URL"


def _required_test_database_url() -> str:
    """Return a guarded PostgreSQL test URL or skip the integration suite."""

    database_url = os.environ.get(TEST_DATABASE_URL_ENV)
    if database_url is None:
        pytest.skip(
            f"{TEST_DATABASE_URL_ENV} is not set; start the Compose test database "
            "before running integration tests"
        )

    parsed_url = make_url(database_url)
    if parsed_url.get_backend_name() != "postgresql":
        pytest.fail(f"{TEST_DATABASE_URL_ENV} must use PostgreSQL")

    database_name = parsed_url.database
    if database_name is None or "test" not in database_name.lower():
        pytest.fail(f"{TEST_DATABASE_URL_ENV} must name an isolated test database")

    return database_url


def _upgrade_database(database_url: str) -> None:
    """Run Alembic using the guarded test URL without changing app defaults."""

    previous_database_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = database_url
    get_settings.cache_clear()

    try:
        command.upgrade(Config(str(PROJECT_ROOT / "alembic.ini")), "head")
    finally:
        if previous_database_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_database_url
        get_settings.cache_clear()


@pytest.fixture(scope="session")
def migrated_engine() -> Iterator[Engine]:
    """Provide an engine after applying every migration to the test database."""

    database_url = _required_test_database_url()
    _upgrade_database(database_url)
    engine = create_engine(database_url, pool_pre_ping=True)

    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT 1")) == 1
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """Expose an empty application schema and restore prior rows after each test."""

    with migrated_engine.connect() as connection:
        outer_transaction = connection.begin()
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())
        session = Session(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )

        try:
            yield session
        finally:
            session.close()
            if outer_transaction.is_active:
                outer_transaction.rollback()
