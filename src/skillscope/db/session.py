"""SQLAlchemy engine and session lifecycle helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from skillscope.core.config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Build one process-wide connection pool lazily."""

    return create_engine(
        str(get_settings().database_url),
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the configured factory for short-lived sessions."""

    return sessionmaker(
        bind=get_engine(),
        autoflush=False,
        expire_on_commit=False,
    )


def get_session() -> Iterator[Session]:
    """Yield a session suitable for dependency injection."""

    with get_session_factory()() as session:
        yield session


@contextmanager
def session_scope() -> Iterator[Session]:
    """Commit a successful unit of work and roll back failures."""

    with get_session_factory()() as session:
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
