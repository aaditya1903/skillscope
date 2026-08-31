"""Tests for validated environment settings."""

import pytest
from pydantic import ValidationError

from skillscope.core.config import Settings


def test_settings_have_safe_development_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.github_token is None
    assert settings.database_url.startswith("postgresql+psycopg://")


def test_github_token_is_masked() -> None:
    settings = Settings(_env_file=None, github_token="not-a-real-token")

    assert settings.github_token is not None
    assert str(settings.github_token) == "**********"


def test_frontend_origin_is_normalized_without_a_trailing_slash() -> None:
    settings = Settings(_env_file=None, frontend_origin="https://example.test/")

    assert settings.frontend_origin == "https://example.test"


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        "javascript:alert(1)",
        "https://user:password@example.test",
        "https://example.test/application",
        "https://example.test?origin=other",
    ],
)
def test_frontend_origin_rejects_wildcards_credentials_and_non_origins(
    origin: str,
) -> None:
    with pytest.raises(ValidationError, match="exact HTTP"):
        Settings(_env_file=None, frontend_origin=origin)
