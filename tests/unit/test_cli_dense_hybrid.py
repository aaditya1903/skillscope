"""CLI routing coverage for dense indexing, search, and method comparison."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from skillscope import cli as cli_module
from skillscope.db.enums import RetrievalMethod

runner = CliRunner()


def test_dense_index_command_routes_the_pinned_config(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_index(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"operation": "index_dense", "indexed_count": 144}

    monkeypatch.setattr(cli_module, "_index_dense_embeddings", fake_index)

    result = runner.invoke(
        cli_module.app,
        ["index", "dense", "--config", "config/retrieval/dense-hybrid-v1.json"],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config/retrieval/dense-hybrid-v1.json"),
    }
    assert '"indexed_count": 144' in result.stdout


def test_search_routes_dense_mode_without_changing_bm25_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_search(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"operation": "search", "method": "dense", "results": []}

    monkeypatch.setattr(cli_module, "_search_dense_or_hybrid", fake_search)

    result = runner.invoke(
        cli_module.app,
        ["search", "semantic query", "--mode", "dense", "--top-k", "7"],
    )

    assert result.exit_code == 0
    assert captured == {
        "query": "semantic query",
        "top_k": 7,
        "mode": RetrievalMethod.DENSE,
        "config_path": Path("config/retrieval/dense-hybrid-v1.json"),
    }


def test_compare_command_routes_explicit_test_release(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_compare(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"operation": "evaluation_compare", "split": "test"}

    monkeypatch.setattr(cli_module, "_evaluate_method_comparison", fake_compare)
    monkeypatch.setattr(cli_module, "_current_git_commit", lambda: "a" * 40)

    result = runner.invoke(
        cli_module.app,
        [
            "evaluate",
            "compare",
            "--split",
            "test",
            "--allow-test",
            "--output",
            "reports/evaluation/method-comparison-test-v1.json",
        ],
    )

    assert result.exit_code == 0
    assert captured["split"].value == "test"
    assert captured["allow_test"] is True
    assert captured["output_path"] == Path("reports/evaluation/method-comparison-test-v1.json")
    assert captured["git_commit"] == "a" * 40
