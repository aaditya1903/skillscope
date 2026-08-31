"""Tests for the command-line interface."""

from typing import Any

import pytest
from typer.testing import CliRunner

from skillscope.cli import app

runner = CliRunner()


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])

    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_serve_disables_the_url_recording_uvicorn_access_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorded: dict[str, Any] = {}

    def fake_run(target: str, **keyword_arguments: Any) -> None:
        recorded["target"] = target
        recorded.update(keyword_arguments)

    monkeypatch.setattr("skillscope.cli.uvicorn.run", fake_run)

    result = runner.invoke(app, ["serve", "--port", "8123"])

    assert result.exit_code == 0
    assert recorded["target"] == "skillscope.api.main:app"
    assert recorded["port"] == 8123
    assert recorded["access_log"] is False
