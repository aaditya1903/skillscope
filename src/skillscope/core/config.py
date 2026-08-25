"""Environment-backed application configuration."""

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from skillscope import __version__


class Settings(BaseSettings):
    """Validated application settings loaded from environment variables."""

    app_name: str = "SkillScope"
    app_version: str = __version__
    environment: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "postgresql+psycopg://skillscope:skillscope@localhost:5432/skillscope"
    frontend_origin: str = "http://localhost:5173"
    github_token: SecretStr | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings instance per process."""
    return Settings()
