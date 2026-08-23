"""Unit tests for lazy engine and session lifecycle configuration."""

import pytest

from skillscope.db.session import get_engine, get_session_factory, session_scope


def test_engine_and_session_factory_are_cached_and_configured() -> None:
    engine = get_engine()
    factory = get_session_factory()

    assert get_engine() is engine
    assert get_session_factory() is factory
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"

    with factory() as session:
        assert session.bind is engine
        assert session.autoflush is False
        assert session.expire_on_commit is False


def test_session_scope_propagates_errors_after_rollback() -> None:
    with pytest.raises(RuntimeError, match="rollback probe"):
        with session_scope():
            raise RuntimeError("rollback probe")
