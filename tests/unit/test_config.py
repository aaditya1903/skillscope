"""Tests for validated environment settings."""

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
