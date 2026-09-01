"""Tests for the settings that select which frozen evidence the API serves."""

from __future__ import annotations

import pytest

from skillscope.api.dependencies import get_api_service
from skillscope.core.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_caches() -> None:
    get_settings.cache_clear()
    get_api_service.cache_clear()


def test_evidence_paths_default_to_the_evaluated_corpus() -> None:
    settings = Settings(_env_file=None)

    assert settings.bm25_config_path == "config/retrieval/bm25-v1.json"
    assert settings.dense_config_path == "config/retrieval/dense-hybrid-v1.json"
    assert settings.evaluation_report_path == ("reports/evaluation/method-comparison-test-v1.json")


def test_service_serves_the_evidence_the_environment_selects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BM25_CONFIG_PATH", "config/demo/bm25-v1.json")
    monkeypatch.setenv("DENSE_CONFIG_PATH", "config/demo/dense-hybrid-v1.json")

    service = get_api_service()

    assert service.bm25_config_path.name == "bm25-v1.json"
    assert service.bm25_config_path.parent.name == "demo"
    assert service.dense_config_path.parent.name == "demo"


def test_service_rejects_an_evidence_path_outside_the_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BM25_CONFIG_PATH", "../elsewhere/bm25.json")

    with pytest.raises(ValueError, match="project-relative"):
        get_api_service()
