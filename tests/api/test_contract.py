"""End-to-end HTTP contract, error, leakage, and OpenAPI tests."""

from __future__ import annotations

import re
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from skillscope.api.dependencies import get_api_service, get_search_capacity
from skillscope.api.service import ApiServiceUnavailableError
from skillscope.db.enums import LicenseStatus, RetrievalMethod, ValidationStatus
from tests.api.conftest import SKILL_ID, FakeApiService, RejectingCapacity


@pytest.mark.parametrize("mode", list(RetrievalMethod))
def test_search_supports_every_mode_with_mode_specific_explanations(
    api_client: TestClient,
    fake_service: FakeApiService,
    mode: RetrievalMethod,
) -> None:
    response = api_client.get(
        "/api/v1/search",
        params={
            "q": "  create a spreadsheet  ",
            "mode": mode.value,
            "limit": 7,
            "license_status": "permissive",
            "validation_status": "valid",
            "has_scripts": "true",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["query"] == "create a spreadsheet"
    assert payload["mode"] == mode.value
    assert payload["limit"] == 7
    assert payload["results"][0]["score_components"]["method"] == mode.value
    assert payload["dataset_snapshot"]["sha256"] == "a" * 64
    assert re.fullmatch(r"[0-9a-f]{32}", response.headers["X-Request-ID"])
    assert payload["request_id"] == response.headers["X-Request-ID"]

    filters = fake_service.last_search["filters"]
    assert filters.license_statuses == frozenset({LicenseStatus.PERMISSIVE})
    assert filters.validation_statuses == frozenset({ValidationStatus.VALID})
    assert filters.has_scripts is True


def test_search_defaults_to_held_out_winner_bm25(api_client: TestClient) -> None:
    response = api_client.get("/api/v1/search", params={"q": "test a web app"})

    assert response.status_code == 200
    assert response.json()["mode"] == "bm25"


@pytest.mark.parametrize(
    ("params", "expected_status"),
    [
        ({"q": "   "}, 400),
        ({}, 422),
        ({"q": "x", "mode": "unknown"}, 422),
        ({"q": "x", "limit": 0}, 422),
        ({"q": "x", "limit": 51}, 422),
        ({"q": "x" * 501}, 422),
    ],
)
def test_search_rejects_invalid_parameters_with_structured_errors(
    api_client: TestClient,
    params: dict[str, object],
    expected_status: int,
) -> None:
    response = api_client.get("/api/v1/search", params=params)

    assert response.status_code == expected_status
    payload = response.json()
    assert set(payload) == {"request_id", "error"}
    assert isinstance(payload["error"]["code"], str)
    assert "traceback" not in response.text.casefold()
    assert "x" * 501 not in response.text


def test_search_returns_429_without_releasing_an_unacquired_slot(
    api_client: TestClient,
) -> None:
    application = api_client.app
    rejecting = RejectingCapacity()
    application.dependency_overrides[get_search_capacity] = lambda: rejecting

    response = api_client.get("/api/v1/search", params={"q": "spreadsheet"})

    assert response.status_code == 429
    assert response.headers["Retry-After"] == "1"
    assert response.json()["error"]["code"] == "search_capacity_exhausted"
    assert rejecting.released is False


def test_liveness_and_readiness_have_distinct_failure_semantics(
    api_client: TestClient,
    fake_service: FakeApiService,
) -> None:
    fake_service.ready = False

    liveness = api_client.get("/healthz")
    readiness = api_client.get("/readyz")

    assert liveness.status_code == 200
    assert liveness.json()["status"] == "ok"
    assert readiness.status_code == 503
    assert readiness.json()["status"] == "not_ready"
    assert readiness.json()["checks"]["database"]["status"] == "failed"


def test_skill_detail_is_bounded_and_body_free(api_client: TestClient) -> None:
    response = api_client.get(f"/api/v1/skills/{SKILL_ID}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["excerpt"] == "Bounded inert plain text."
    assert payload["excerpt_truncated"] is True
    assert payload["supporting_files"][0]["relative_path"] == "scripts/check.py"
    assert "body_text" not in payload
    assert "content" not in payload["supporting_files"][0]


def test_missing_and_invalid_skill_ids_use_typed_errors(api_client: TestClient) -> None:
    missing = api_client.get(f"/api/v1/skills/{uuid4()}")
    invalid = api_client.get("/api/v1/skills/not-a-uuid")

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "skill_not_found"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "request_validation_failed"


def test_stats_and_latest_evaluation_are_versioned_safe_summaries(
    api_client: TestClient,
) -> None:
    stats = api_client.get("/api/v1/stats")
    evaluation = api_client.get("/api/v1/evaluations/latest")

    assert stats.status_code == 200
    assert stats.json()["retrieval_eligible_skill_count"] == 1
    assert evaluation.status_code == 200
    assert [item["method"] for item in evaluation.json()["methods"]] == [
        "bm25",
        "dense",
        "hybrid",
    ]
    assert "queries" not in evaluation.json()


def test_dependency_errors_never_leak_secrets_or_stack_traces(
    api_client: TestClient,
) -> None:
    secret = "github_pat_NEVER_RETURN_THIS"

    class FailingService(FakeApiService):
        def search(self, *args: object, **kwargs: object) -> object:
            raise ApiServiceUnavailableError(f"postgresql://user:{secret}@db/raw skill body")

    api_client.app.dependency_overrides[get_api_service] = FailingService
    response = api_client.get("/api/v1/search", params={"q": "safe query"})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "retrieval_unavailable"
    assert secret not in response.text
    assert "raw skill body" not in response.text
    assert "traceback" not in response.text.casefold()


def test_unexpected_errors_use_a_generic_500_envelope(api_client: TestClient) -> None:
    secret = "super-secret-token"

    class ExplodingService(FakeApiService):
        def stats(self, *args: object, **kwargs: object) -> object:
            raise RuntimeError(f"{secret}\nraw upstream body")

    api_client.app.dependency_overrides[get_api_service] = ExplodingService
    response = api_client.get("/api/v1/stats")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert secret not in response.text
    assert "raw upstream body" not in response.text


def test_cors_allows_only_the_configured_frontend_origin(api_client: TestClient) -> None:
    allowed = api_client.options(
        "/api/v1/search",
        headers={
            "Origin": "http://frontend.example",
            "Access-Control-Request-Method": "GET",
        },
    )
    denied = api_client.options(
        "/api/v1/search",
        headers={
            "Origin": "http://attacker.example",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert allowed.headers["access-control-allow-origin"] == "http://frontend.example"
    assert "access-control-allow-origin" not in denied.headers


def test_openapi_matches_runtime_paths_parameters_and_error_models(
    api_client: TestClient,
) -> None:
    response = api_client.get("/openapi.json")

    assert response.status_code == 200
    schema = response.json()
    expected_paths = {
        "/healthz",
        "/readyz",
        "/api/v1/search",
        "/api/v1/skills/{skill_id}",
        "/api/v1/stats",
        "/api/v1/evaluations/latest",
    }
    assert expected_paths <= set(schema["paths"])
    search = schema["paths"]["/api/v1/search"]["get"]
    parameters = {item["name"]: item for item in search["parameters"]}
    assert parameters["q"]["required"] is True
    assert parameters["limit"]["schema"]["maximum"] == 50
    assert {"200", "400", "422", "429", "503"} <= set(search["responses"])
    component_names = set(schema["components"]["schemas"])
    assert {
        "SearchResponse",
        "SkillDetailResponse",
        "StatsResponse",
        "LatestEvaluationResponse",
        "ErrorResponse",
    } <= component_names
