"""Environment-backed application configuration."""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
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

    # Serving reads these three files. The defaults are the frozen evaluated
    # corpus; the demonstration stack points them at its own generated evidence.
    bm25_config_path: str = "config/retrieval/bm25-v1.json"
    dense_config_path: str = "config/retrieval/dense-hybrid-v1.json"
    evaluation_report_path: str = "reports/evaluation/method-comparison-test-v1.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("frontend_origin")
    @classmethod
    def validate_frontend_origin(cls, value: str) -> str:
        """Require one exact HTTP(S) origin rather than a wildcard or URL path."""

        normalized = value.strip()
        parsed = urlsplit(normalized)
        try:
            parsed_port = parsed.port
        except ValueError as error:
            raise ValueError("frontend_origin contains an invalid port") from error
        if (
            normalized == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (":" in parsed.netloc and parsed_port is None)
        ):
            raise ValueError("frontend_origin must be one exact HTTP(S) origin")
        return normalized.rstrip("/")


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings instance per process."""
    return Settings()
