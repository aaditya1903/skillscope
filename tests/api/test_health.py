"""Tests for liveness and API schema exposure."""

from fastapi.testclient import TestClient

from skillscope.api.main import app

client = TestClient(app)


def test_healthz_reports_process_liveness() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "SkillScope",
        "version": "0.1.0",
    }


def test_healthz_is_present_in_openapi_schema() -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert "/healthz" in response.json()["paths"]
