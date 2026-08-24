"""CLI routing coverage for the deterministic BM25 search command."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from skillscope import cli as cli_module
from skillscope.retrieval.corpus import StaleCorpusError

runner = CliRunner()


def test_search_command_routes_query_limits_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_search(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {
            "operation": "search",
            "method": "bm25",
            "query": arguments["query"],
            "results": [{"rank": 1, "name": "xlsx"}],
        }

    monkeypatch.setattr(cli_module, "_search_bm25", fake_search)

    result = runner.invoke(
        cli_module.app,
        [
            "search",
            "edit spreadsheets",
            "--top-k",
            "5",
            "--config",
            "config/retrieval/bm25-v1.json",
            "--snapshot",
            "data/manifests/dataset-snapshot.jsonl",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "query": "edit spreadsheets",
        "top_k": 5,
        "config_path": Path("config/retrieval/bm25-v1.json"),
        "snapshot_path": Path("data/manifests/dataset-snapshot.jsonl"),
    }
    assert '"method": "bm25"' in result.stdout
    assert '"name": "xlsx"' in result.stdout


def test_search_command_reports_stale_corpus_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_search(**arguments: object) -> dict[str, object]:
        raise StaleCorpusError("dataset snapshot is stale")

    monkeypatch.setattr(cli_module, "_search_bm25", fake_search)

    result = runner.invoke(cli_module.app, ["search", "spreadsheets"])

    assert result.exit_code == 1
    assert "Error: dataset snapshot is stale" in result.stdout
    assert "Traceback" not in result.stdout
