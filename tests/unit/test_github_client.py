"""Mocked tests for the bounded GitHub REST transport."""

from __future__ import annotations

import asyncio
import logging
import traceback
from datetime import UTC, datetime

import httpx
import pytest
import respx

from skillscope.core.logging import JsonFormatter
from skillscope.ingestion.github_client import (
    GITHUB_API_VERSION,
    GitHubAuthenticationError,
    GitHubClient,
    GitHubNotFoundError,
    GitHubPayloadError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubResponseError,
    GitHubTransportError,
)
from skillscope.ingestion.rate_limit import GitHubRateLimitSnapshot

TOKEN = "not-a-real-token-sensitive-marker"
RATE_LIMIT_PAYLOAD = {
    "resources": {
        "core": {"limit": 5_000, "used": 10, "remaining": 4_990, "reset": 1_787_517_225},
        "search": {"limit": 30, "used": 1, "remaining": 29, "reset": 1_787_513_685},
        "code_search": {"limit": 10, "used": 1, "remaining": 9, "reset": 1_787_513_685},
    }
}
REPOSITORY_PAYLOAD = {
    "id": 1_061_953_414,
    "owner": {
        "login": "anthropics",
        "id": 1,
        "html_url": "https://github.com/anthropics",
    },
    "name": "skills",
    "full_name": "anthropics/skills",
    "private": False,
    "html_url": "https://github.com/anthropics/skills",
    "default_branch": "main",
    "description": "Public repository for Agent Skills",
    "stargazers_count": 171_000,
    "forks_count": 20_000,
    "open_issues_count": 325,
    "fork": False,
    "archived": False,
    "license": None,
    "pushed_at": "2026-08-23T18:00:00Z",
}


async def _no_sleep(_: float) -> None:
    return None


@pytest.mark.asyncio
async def test_rate_limit_request_is_authenticated_versioned_and_typed() -> None:
    response_headers = {
        "ETag": '"rate-etag"',
        "X-RateLimit-Limit": "5000",
        "X-RateLimit-Used": "10",
        "X-RateLimit-Remaining": "4990",
        "X-RateLimit-Reset": "1787517225",
        "X-RateLimit-Resource": "core",
    }

    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(200, json=RATE_LIMIT_PAYLOAD, headers=response_headers)
            )
            client = GitHubClient(TOKEN, client=http_client)

            result = await client.get_rate_limits()

    request = route.calls[0].request
    assert request.headers["authorization"] == f"Bearer {TOKEN}"
    assert request.headers["accept"] == "application/vnd.github+json"
    assert request.headers["x-github-api-version"] == GITHUB_API_VERSION
    assert request.headers["user-agent"].startswith("SkillScope/")
    assert result.data.resources.core.remaining == 4_990
    assert result.etag == '"rate-etag"'
    assert result.rate_limit.resource == "core"
    assert len(result.correlation_id) == 32


@pytest.mark.asyncio
async def test_repository_identifiers_are_validated_before_request() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=False) as router:
            route = router.get("https://api.github.com/repos/anthropics/skills").mock(
                return_value=httpx.Response(200, json=REPOSITORY_PAYLOAD)
            )
            client = GitHubClient(TOKEN, client=http_client)

            with pytest.raises(ValueError):
                await client.get_repository("../anthropics", "skills")

    assert route.call_count == 0


@pytest.mark.asyncio
async def test_selected_server_error_is_retried_with_bounded_backoff() -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/repos/anthropics/skills").mock(
                side_effect=[
                    httpx.Response(500, json={"message": "temporary"}),
                    httpx.Response(200, json=REPOSITORY_PAYLOAD),
                ]
            )
            client = GitHubClient(
                TOKEN,
                client=http_client,
                sleep=record_sleep,
                random_source=lambda: 0.0,
            )

            result = await client.get_repository("anthropics", "skills")

    assert route.call_count == 2
    assert delays == [0.5]
    assert result.data.full_name == "anthropics/skills"


@pytest.mark.asyncio
async def test_transport_timeout_is_bounded_and_redacted() -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                side_effect=httpx.ReadTimeout(f"unsafe upstream detail {TOKEN}")
            )
            client = GitHubClient(
                TOKEN,
                client=http_client,
                max_attempts=2,
                sleep=record_sleep,
                random_source=lambda: 0.0,
            )

            with pytest.raises(GitHubTransportError) as caught:
                await client.get_rate_limits()

    rendered_traceback = "".join(traceback.format_exception(caught.value))
    assert route.call_count == 2
    assert delays == [0.5]
    assert caught.value.retryable
    assert TOKEN not in str(caught.value)
    assert TOKEN not in rendered_traceback


@pytest.mark.asyncio
async def test_429_honours_retry_after_before_retrying() -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                side_effect=[
                    httpx.Response(
                        429, json={"message": "slow down"}, headers={"Retry-After": "2"}
                    ),
                    httpx.Response(200, json=RATE_LIMIT_PAYLOAD),
                ]
            )
            client = GitHubClient(TOKEN, client=http_client, sleep=record_sleep)

            await client.get_rate_limits()

    assert route.call_count == 2
    assert delays == [2.0]


@pytest.mark.asyncio
async def test_429_without_hint_uses_bounded_github_fallback() -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                side_effect=[
                    httpx.Response(429, json={"message": "secondary limit"}),
                    httpx.Response(200, json=RATE_LIMIT_PAYLOAD),
                ]
            )
            client = GitHubClient(TOKEN, client=http_client, sleep=record_sleep)

            await client.get_rate_limits()

    assert route.call_count == 2
    assert delays == [60.0]


@pytest.mark.asyncio
async def test_429_delay_above_configured_bound_is_returned_to_caller() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(
                    429,
                    json={"message": "wait"},
                    headers={"Retry-After": "61"},
                )
            )
            client = GitHubClient(TOKEN, client=http_client, sleep=_no_sleep)

            with pytest.raises(GitHubRateLimitError) as caught:
                await client.get_rate_limits()

    assert route.call_count == 1
    assert caught.value.rate_limit is not None
    assert caught.value.rate_limit.retry_after_seconds == 61


@pytest.mark.asyncio
async def test_primary_rate_limit_is_resumable_but_not_blindly_retried() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(
                    403,
                    json={"message": "API rate limit exceeded"},
                    headers={
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": "1787517225",
                        "X-RateLimit-Resource": "core",
                    },
                )
            )
            client = GitHubClient(TOKEN, client=http_client, sleep=_no_sleep)

            with pytest.raises(GitHubRateLimitError) as caught:
                await client.get_rate_limits()

    assert route.call_count == 1
    assert caught.value.status_code == 403
    assert caught.value.retryable
    assert caught.value.rate_limit is not None
    assert caught.value.rate_limit.exhausted


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(401, GitHubAuthenticationError), (404, GitHubNotFoundError)],
)
async def test_non_retryable_responses_fail_once(
    status_code: int,
    error_type: type[Exception],
) -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(status_code, json={"message": "no"})
            )
            client = GitHubClient(TOKEN, client=http_client, sleep=_no_sleep)

            with pytest.raises(error_type):
                await client.get_rate_limits()

    assert route.call_count == 1


@pytest.mark.asyncio
async def test_permission_error_without_rate_headers_is_not_retried() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(403, json={"message": "forbidden"})
            )
            client = GitHubClient(TOKEN, client=http_client, sleep=_no_sleep)

            with pytest.raises(GitHubPermissionError) as caught:
                await client.get_rate_limits()

    assert route.call_count == 1
    assert not caught.value.retryable


@pytest.mark.asyncio
async def test_malformed_success_payload_has_safe_error() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(200, content=b"{")
            )
            client = GitHubClient(TOKEN, client=http_client)

            with pytest.raises(GitHubPayloadError) as caught:
                await client.get_rate_limits()

    assert TOKEN not in str(caught.value)
    assert caught.value.status_code == 200


@pytest.mark.asyncio
async def test_schema_mismatch_has_safe_error_without_response_body() -> None:
    unsafe_value = f"untrusted-{TOKEN}"

    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(200, json={"resources": unsafe_value})
            )
            client = GitHubClient(TOKEN, client=http_client)

            with pytest.raises(GitHubPayloadError) as caught:
                await client.get_rate_limits()

    rendered_traceback = "".join(traceback.format_exception(caught.value))
    assert unsafe_value not in str(caught.value)
    assert unsafe_value not in rendered_traceback


@pytest.mark.asyncio
async def test_debug_logs_include_correlation_context_but_never_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    logger = logging.getLogger("skillscope.ingestion.github_client")
    caplog.set_level(logging.DEBUG, logger=logger.name)
    logger.addHandler(caplog.handler)
    try:
        async with httpx.AsyncClient(trust_env=False) as http_client:
            with respx.mock(assert_all_called=True) as router:
                router.get("https://api.github.com/rate_limit").mock(
                    return_value=httpx.Response(401, json={"message": "bad credentials"})
                )
                client = GitHubClient(TOKEN, client=http_client)

                with pytest.raises(GitHubAuthenticationError) as caught:
                    await client.get_rate_limits()
    finally:
        logger.removeHandler(caplog.handler)

    rendered = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    assert TOKEN not in rendered
    assert TOKEN not in str(caught.value)
    assert caught.value.correlation_id in rendered
    assert '"http_status": 401' in rendered


@pytest.mark.asyncio
async def test_redirect_to_non_github_host_is_rejected_before_following() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            route = router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(
                    302, headers={"Location": "https://evil.example/collect"}
                )
            )
            client = GitHubClient(TOKEN, client=http_client)

            with pytest.raises(GitHubResponseError, match=r"allowlisted API host"):
                await client.get_rate_limits()

    assert route.call_count == 1


@pytest.mark.asyncio
async def test_redirect_within_github_api_host_is_followed() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=True) as router:
            first = router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(301, headers={"Location": "/rate_limit/current"})
            )
            second = router.get("https://api.github.com/rate_limit/current").mock(
                return_value=httpx.Response(200, json=RATE_LIMIT_PAYLOAD)
            )
            client = GitHubClient(TOKEN, client=http_client)

            result = await client.get_rate_limits()

    assert first.call_count == 1
    assert second.call_count == 1
    assert result.data.resources.core.limit == 5_000


def test_rate_limit_parser_is_case_insensitive_and_tolerates_malformed_values() -> None:
    snapshot = GitHubRateLimitSnapshot.from_headers(
        {
            "X-RateLimit-Limit": "not-an-int",
            "x-RATELIMIT-remaining": "0",
            "X-RateLimit-Reset": "1787517225",
            "Retry-After": "3",
        }
    )

    assert snapshot.limit is None
    assert snapshot.exhausted
    assert snapshot.retry_after_seconds == 3
    assert snapshot.retry_delay_seconds(now=datetime(2026, 8, 23, tzinfo=UTC)) == 3.0


def test_rate_limit_reset_produces_non_negative_delay() -> None:
    now = datetime(2026, 8, 23, 20, 0, tzinfo=UTC)
    reset = int(now.timestamp()) + 30
    snapshot = GitHubRateLimitSnapshot.from_headers(
        {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": str(reset),
        }
    )

    assert snapshot.retry_delay_seconds(now=now) == 30.0
    assert snapshot.retry_delay_seconds(now=datetime(2026, 8, 23, 20, 1, tzinfo=UTC)) == 0.0


def test_rate_limit_parser_discards_impossible_reset_timestamp() -> None:
    snapshot = GitHubRateLimitSnapshot.from_headers(
        {
            "X-RateLimit-Remaining": "0",
            "X-RateLimit-Reset": "999999999999999999999999999999999",
        }
    )

    assert snapshot.reset_at is None
    assert snapshot.retry_delay_seconds() is None


@pytest.mark.asyncio
async def test_concurrency_never_exceeds_configured_bound() -> None:
    active_requests = 0
    peak_requests = 0
    release = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal active_requests, peak_requests
        active_requests += 1
        peak_requests = max(peak_requests, active_requests)
        if active_requests == 5:
            release.set()
        await release.wait()
        active_requests -= 1
        return httpx.Response(200, json=RATE_LIMIT_PAYLOAD, request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, trust_env=False) as http_client:
        client = GitHubClient(TOKEN, client=http_client, max_concurrency=5)
        responses = await asyncio.gather(*(client.get_rate_limits() for _ in range(6)))

    assert len(responses) == 6
    assert peak_requests == 5


@pytest.mark.parametrize(
    ("parameter", "value"),
    [
        ("timeout_seconds", 0),
        ("timeout_seconds", 121),
        ("max_attempts", 0),
        ("max_attempts", 6),
        ("max_concurrency", 0),
        ("max_concurrency", 21),
        ("max_retry_delay_seconds", 0),
        ("max_retry_delay_seconds", 301),
    ],
)
def test_client_rejects_unbounded_or_invalid_configuration(parameter: str, value: int) -> None:
    with pytest.raises(ValueError):
        GitHubClient(TOKEN, **{parameter: value})  # type: ignore[arg-type]


def test_client_rejects_empty_token() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        GitHubClient("   ")


@pytest.mark.asyncio
async def test_excessive_redirects_raise_safe_client_error() -> None:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        with respx.mock(assert_all_called=False) as router:
            router.get("https://api.github.com/rate_limit").mock(
                return_value=httpx.Response(302, headers={"Location": "/rate_limit"})
            )
            client = GitHubClient(TOKEN, client=http_client)

            with pytest.raises(GitHubResponseError) as caught:
                await client.get_rate_limits()

    assert TOKEN not in str(caught.value)
