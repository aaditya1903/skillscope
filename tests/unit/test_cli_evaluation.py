"""CLI routing and safe-error coverage for evaluation commands."""

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from skillscope import cli as cli_module

runner = CliRunner()


def test_pool_command_routes_config_and_worksheet(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_pool(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"operation": "evaluation_pool", "candidate_count": 42}

    monkeypatch.setattr(cli_module, "_build_evaluation_pool", fake_pool)

    result = runner.invoke(
        cli_module.app,
        [
            "evaluate",
            "pool",
            "--config",
            "config/evaluation/test.json",
            "--worksheet",
            "/tmp/test-labels.csv",
        ],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config/evaluation/test.json"),
        "worksheet_path": Path("/tmp/test-labels.csv"),
    }
    assert '"candidate_count": 42' in result.stdout


def test_import_labels_routes_the_completed_worksheet(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_import(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"operation": "evaluation_import_labels", "judgement_count": 480}

    monkeypatch.setattr(cli_module, "_import_evaluation_labels", fake_import)

    result = runner.invoke(
        cli_module.app,
        ["evaluate", "import-labels", "/tmp/complete.csv"],
    )

    assert result.exit_code == 0
    assert captured == {
        "config_path": Path("config/evaluation/evaluation-v1.json"),
        "worksheet_path": Path("/tmp/complete.csv"),
    }


def test_bm25_command_keeps_test_unlock_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_evaluate(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"operation": "evaluation_bm25", "split": "test"}

    monkeypatch.setattr(cli_module, "_evaluate_bm25_split", fake_evaluate)
    monkeypatch.setattr(cli_module, "_current_git_commit", lambda: "a" * 40)

    result = runner.invoke(
        cli_module.app,
        [
            "evaluate",
            "bm25",
            "--split",
            "test",
            "--allow-test",
            "--output",
            "reports/evaluation/test.json",
        ],
    )

    assert result.exit_code == 0
    assert captured["split"].value == "test"
    assert captured["allow_test"] is True
    assert captured["output_path"] == Path("reports/evaluation/test.json")
    assert captured["git_commit"] == "a" * 40


def test_evaluation_errors_are_safe_and_traceback_free(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_validate(**arguments: object) -> dict[str, object]:
        raise ValueError("qrels reference a missing skill")

    monkeypatch.setattr(cli_module, "_validate_evaluation_files", fake_validate)

    result = runner.invoke(cli_module.app, ["evaluate", "validate"])

    assert result.exit_code == 1
    assert "Error: qrels reference a missing skill" in result.stdout
    assert "Traceback" not in result.stdout
