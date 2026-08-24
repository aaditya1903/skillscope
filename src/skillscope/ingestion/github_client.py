"""Bounded, read-only transport for the GitHub REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from urllib.parse import urljoin
from uuid import uuid4

import httpx
from pydantic import BaseModel, SecretStr, ValidationError

from skillscope import __version__
from skillscope.ingestion.models import (
    GitHubRateLimitResponsePayload,
    GitHubRepositoryPayload,
)
from skillscope.ingestion.rate_limit import GitHubRateLimitSnapshot
from skillscope.ingestion.validation import (
    validate_github_api_url,
    validate_owner,
    validate_repository_name,
)

GITHUB_API_BASE_URL = "https://api.github.com"
GITHUB_API_VERSION = "2026-03-10"
DEFAULT_MAX_ATTEMPTS = 3
DEFAULT_MAX_CONCURRENCY = 5
DEFAULT_MAX_RETRY_DELAY_SECONDS = 60.0
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_REDIRECTS = 3
MAX_CONFIGURED_ATTEMPTS = 5
MAX_CONFIGURED_CONCURRENCY = 20
MAX_CONFIGURED_RETRY_DELAY_SECONDS = 300.0
MAX_CONFIGURED_TIMEOUT_SECONDS = 120.0

_RETRYABLE_SERVER_STATUSES = frozenset({500, 502, 503, 504})
_REDIRECT_STATUSES = frozenset({301, 302, 307, 308})

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
RandomSource = Callable[[], float]


@dataclass(frozen=True, slots=True)
class GitHubResponse[PayloadT: BaseModel]:
    """Validated payload plus safe response metadata."""

    data: PayloadT
    status_code: int
    etag: str | None
    rate_limit: GitHubRateLimitSnapshot
    correlation_id: str


class GitHubClientError(RuntimeError):
    """Base exception containing only safe operational context."""

    def __init__(
        self,
        message: str,
        *,
        correlation_id: str,
        status_code: int | None = None,
        retryable: bool = False,
        rate_limit: GitHubRateLimitSnapshot | None = None,
    ) -> None:
        super().__init__(f"{message}; correlation_id={correlation_id}")
        self.correlation_id = correlation_id
        self.status_code = status_code
        self.retryable = retryable
        self.rate_limit = rate_limit


class GitHubAuthenticationError(GitHubClientError):
    """The supplied GitHub credential was rejected."""


class GitHubPermissionError(GitHubClientError):
    """The credential cannot access the requested resource."""


class GitHubNotFoundError(GitHubClientError):
    """The requested GitHub resource was not found or was concealed."""


class GitHubRateLimitError(GitHubClientError):
    """GitHub asked the caller to stop until a later time."""


class GitHubResponseError(GitHubClientError):
    """GitHub returned an unsuccessful response."""


class GitHubPayloadError(GitHubClientError):
    """A successful response did not match the expected schema."""


class GitHubTransportError(GitHubClientError):
    """All bounded attempts failed before a response was received."""


class GitHubClient:
    """Authenticated client restricted to known read-only GitHub endpoints."""

    def __init__(
        self,
        token: SecretStr | str,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
        max_retry_delay_seconds: float = DEFAULT_MAX_RETRY_DELAY_SECONDS,
        sleep: Sleep = asyncio.sleep,
        random_source: RandomSource = random.random,
    ) -> None:
        token_value = token.get_secret_value() if isinstance(token, SecretStr) else token
        if not token_value.strip():
            raise ValueError("GitHub token must be non-empty")
        if not 0 < timeout_seconds <= MAX_CONFIGURED_TIMEOUT_SECONDS:
            raise ValueError("timeout_seconds must be in the range 0 < value <= 120")
        if not 1 <= max_attempts <= MAX_CONFIGURED_ATTEMPTS:
            raise ValueError("max_attempts must be in the range 1-5")
        if not 1 <= max_concurrency <= MAX_CONFIGURED_CONCURRENCY:
            raise ValueError("max_concurrency must be in the range 1-20")
        if not 0 < max_retry_delay_seconds <= MAX_CONFIGURED_RETRY_DELAY_SECONDS:
            raise ValueError("max_retry_delay_seconds must be in the range 0 < value <= 300")

        self._authorization = f"Bearer {token_value}"
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self._timeout = httpx.Timeout(timeout_seconds)
        self._max_attempts = max_attempts
        self._max_retry_delay_seconds = max_retry_delay_seconds
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._sleep = sleep
        self._random_source = random_source

    async def __aenter__(self) -> GitHubClient:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Close the internally created HTTP client, if any."""
        if self._owns_client:
            await self._client.aclose()

    async def get_rate_limits(self) -> GitHubResponse[GitHubRateLimitResponsePayload]:
        """Return GitHub's authenticated primary rate-limit buckets."""
        return await self._get_model("/rate_limit", GitHubRateLimitResponsePayload)

    async def get_repository(
        self,
        owner: str,
        repository: str,
    ) -> GitHubResponse[GitHubRepositoryPayload]:
        """Fetch validated public repository metadata."""
        owner = validate_owner(owner)
        repository = validate_repository_name(repository)
        return await self._get_model(
            f"/repos/{owner}/{repository}",
            GitHubRepositoryPayload,
        )

    async def _get_model[PayloadT: BaseModel](
        self,
        endpoint: str,
        payload_type: type[PayloadT],
    ) -> GitHubResponse[PayloadT]:
        correlation_id = uuid4().hex
        response = await self._request(endpoint, correlation_id=correlation_id)
        rate_limit = GitHubRateLimitSnapshot.from_headers(response.headers)

        try:
            raw_payload = response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise GitHubPayloadError(
                "GitHub returned malformed JSON",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            ) from None

        try:
            payload = payload_type.model_validate(raw_payload)
        except ValidationError:
            raise GitHubPayloadError(
                "GitHub response did not match the expected schema",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            ) from None

        return GitHubResponse(
            data=payload,
            status_code=response.status_code,
            etag=response.headers.get("etag"),
            rate_limit=rate_limit,
            correlation_id=correlation_id,
        )

    async def _request(self, endpoint: str, *, correlation_id: str) -> httpx.Response:
        url = validate_github_api_url(urljoin(f"{GITHUB_API_BASE_URL}/", endpoint.lstrip("/")))
        headers = self._request_headers()

        for attempt in range(1, self._max_attempts + 1):
            logger.debug(
                "github_request_started",
                extra={
                    "correlation_id": correlation_id,
                    "http_method": "GET",
                    "attempt": attempt,
                },
            )
            try:
                response = await self._send_with_safe_redirects(
                    url,
                    headers=headers,
                    correlation_id=correlation_id,
                )
            except httpx.TransportError:
                if attempt == self._max_attempts:
                    raise GitHubTransportError(
                        "GitHub request failed after bounded transport retries",
                        correlation_id=correlation_id,
                        retryable=True,
                    ) from None
                await self._wait_before_retry(
                    self._backoff_delay(attempt),
                    correlation_id=correlation_id,
                    attempt=attempt,
                )
                continue

            rate_limit = GitHubRateLimitSnapshot.from_headers(response.headers)
            logger.debug(
                "github_response_received",
                extra={
                    "correlation_id": correlation_id,
                    "http_method": "GET",
                    "http_status": response.status_code,
                    "attempt": attempt,
                    "rate_limit_resource": rate_limit.resource,
                },
            )
            if response.is_success:
                return response

            response_error = self._response_error(
                response.status_code,
                correlation_id=correlation_id,
                rate_limit=rate_limit,
            )
            retry_delay = self._response_retry_delay(
                response.status_code,
                rate_limit=rate_limit,
                attempt=attempt,
            )
            if retry_delay is None or attempt == self._max_attempts:
                raise response_error

            await self._wait_before_retry(
                retry_delay,
                correlation_id=correlation_id,
                attempt=attempt,
            )

        raise AssertionError("bounded request loop exited unexpectedly")

    async def _send_with_safe_redirects(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        correlation_id: str,
    ) -> httpx.Response:
        current_url = url
        for redirect_count in range(MAX_REDIRECTS + 1):
            async with self._semaphore:
                response = await self._client.get(
                    current_url,
                    headers=headers,
                    timeout=self._timeout,
                    follow_redirects=False,
                )
            if response.status_code not in _REDIRECT_STATUSES:
                return response
            if redirect_count == MAX_REDIRECTS:
                break

            location = response.headers.get("location")
            if location is None:
                break
            try:
                current_url = validate_github_api_url(str(response.url.join(location)))
            except ValueError:
                raise GitHubResponseError(
                    "GitHub returned a redirect outside the allowlisted API host",
                    correlation_id=correlation_id,
                    status_code=response.status_code,
                ) from None

        raise GitHubResponseError(
            "GitHub returned an unsafe or excessive redirect",
            correlation_id=correlation_id,
            status_code=response.status_code,
        )

    def _request_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": self._authorization,
            "User-Agent": f"SkillScope/{__version__}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    def _response_error(
        self,
        status_code: int,
        *,
        correlation_id: str,
        rate_limit: GitHubRateLimitSnapshot,
    ) -> GitHubClientError:
        if status_code == 401:
            return GitHubAuthenticationError(
                "GitHub rejected the credential",
                correlation_id=correlation_id,
                status_code=status_code,
                rate_limit=rate_limit,
            )
        if status_code == 404:
            return GitHubNotFoundError(
                "GitHub resource was not found",
                correlation_id=correlation_id,
                status_code=status_code,
                rate_limit=rate_limit,
            )
        if status_code in {403, 429} and (
            status_code == 429 or rate_limit.exhausted or rate_limit.retry_after_seconds is not None
        ):
            return GitHubRateLimitError(
                "GitHub rate limit prevented the request",
                correlation_id=correlation_id,
                status_code=status_code,
                retryable=True,
                rate_limit=rate_limit,
            )
        if status_code == 403:
            return GitHubPermissionError(
                "GitHub denied access to the resource",
                correlation_id=correlation_id,
                status_code=status_code,
                rate_limit=rate_limit,
            )
        return GitHubResponseError(
            f"GitHub request failed with HTTP {status_code}",
            correlation_id=correlation_id,
            status_code=status_code,
            retryable=status_code in _RETRYABLE_SERVER_STATUSES,
            rate_limit=rate_limit,
        )

    def _response_retry_delay(
        self,
        status_code: int,
        *,
        rate_limit: GitHubRateLimitSnapshot,
        attempt: int,
    ) -> float | None:
        if status_code in _RETRYABLE_SERVER_STATUSES:
            return self._backoff_delay(attempt)
        if status_code != 429:
            return None

        requested_delay = rate_limit.retry_delay_seconds()
        if requested_delay is None:
            requested_delay = DEFAULT_MAX_RETRY_DELAY_SECONDS
        if requested_delay > self._max_retry_delay_seconds:
            return None
        return requested_delay

    def _backoff_delay(self, attempt: int) -> float:
        base_delay = min(0.5 * (2 ** (attempt - 1)), self._max_retry_delay_seconds)
        random_value = min(max(self._random_source(), 0.0), 1.0)
        jitter = base_delay * 0.25 * random_value
        return float(min(base_delay + jitter, self._max_retry_delay_seconds))

    async def _wait_before_retry(
        self,
        delay: float,
        *,
        correlation_id: str,
        attempt: int,
    ) -> None:
        logger.debug(
            "github_retry_scheduled",
            extra={
                "correlation_id": correlation_id,
                "attempt": attempt,
                "retry_delay_seconds": delay,
            },
        )
        await self._sleep(delay)
