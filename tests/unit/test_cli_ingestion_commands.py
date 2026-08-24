"""CLI routing tests for batched discovery and ingestion operations."""

from typing import Any

import pytest
from typer.testing import CliRunner

from skillscope import cli as cli_module

runner = CliRunner()


@pytest.fixture(autouse=True)
def fixed_git_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_module, "_current_git_commit", lambda: "a" * 40)


def test_discover_command_routes_bounded_options(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def fake_discover(**arguments: object) -> dict[str, object]:
        captured.update(arguments)
        return {"operation": "discover", "candidate_count": 20}

    monkeypatch.setattr(cli_module, "_discover_candidates", fake_discover)

    result = runner.invoke(
        cli_module.app,
        ["ingest", "discover", "--target-skills", "20", "--per-page", "50"],
    )

    assert result.exit_code == 0
    assert captured["target_skills"] == 20
    assert captured["per_page"] == 50
    assert '"candidate_count": 20' in result.stdout


def test_run_command_can_fail_after_writing_safe_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_run(**arguments: object) -> dict[str, object]:
        assert arguments["manifest_path"]
        assert arguments["snapshot_path"]
        return {
            "operation": "ingest",
            "error_count": 1,
            "failures": [{"category": "payload"}],
        }

    monkeypatch.setattr(cli_module, "_run_candidate_manifest", fake_run)

    result = runner.invoke(
        cli_module.app,
        ["ingest", "run", "--fail-on-errors"],
    )

    assert result.exit_code == 2
    assert '"error_count": 1' in result.stdout
    assert '"category": "payload"' in result.stdout
