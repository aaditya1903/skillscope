"""Bounded, read-only transport for the GitHub REST API."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, urlencode, urljoin
from uuid import uuid4

import httpx
from pydantic import BaseModel, SecretStr, TypeAdapter, ValidationError

from skillscope import __version__
from skillscope.ingestion.models import (
    GitHubCodeSearchResponsePayload,
    GitHubDirectoryEntryPayload,
    GitHubFilePayload,
    GitHubRateLimitResponsePayload,
    GitHubRepositoryPayload,
)
from skillscope.ingestion.rate_limit import GitHubRateLimitSnapshot
from skillscope.ingestion.validation import (
    validate_git_ref,
    validate_github_api_url,
    validate_owner,
    validate_relative_path,
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
MAX_CODE_SEARCH_PAGES = 10
MAX_CODE_SEARCH_QUERY_CHARACTERS = 256
MAX_CODE_SEARCH_RESULTS = 1_000
MAX_DIRECTORY_ENTRIES = 1_000
MAX_DIRECTORY_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_ETAG_BYTES = 512
MAX_SKILL_FILE_RESPONSE_BYTES = 384 * 1024
MAX_SKILL_FILE_SIZE_BYTES = 256 * 1024

_RETRYABLE_SERVER_STATUSES = frozenset({500, 502, 503, 504})
_REDIRECT_STATUSES = frozenset({301, 302, 307, 308})

logger = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]
RandomSource = Callable[[], float]
_DIRECTORY_ENTRIES_ADAPTER: TypeAdapter[tuple[GitHubDirectoryEntryPayload, ...]] = TypeAdapter(
    tuple[GitHubDirectoryEntryPayload, ...]
)


@dataclass(frozen=True, slots=True)
class GitHubResponse[PayloadT]:
    """Validated payload plus safe response metadata."""

    data: PayloadT
    status_code: int
    etag: str | None
    rate_limit: GitHubRateLimitSnapshot
    correlation_id: str
    next_url: str | None = None


@dataclass(frozen=True, slots=True)
class GitHubNotModifiedResponse:
    """Metadata returned when a conditional GitHub request receives HTTP 304."""

    etag: str | None
    rate_limit: GitHubRateLimitSnapshot
    correlation_id: str
    status_code: Literal[304] = 304


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


class GitHubPayloadTooLargeError(GitHubClientError):
    """A GitHub payload exceeded a configured ingestion safety bound."""


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

    async def search_skill_files(
        self,
        query: str,
        *,
        page: int = 1,
        per_page: int = 100,
    ) -> GitHubResponse[GitHubCodeSearchResponsePayload]:
        """Return one validated GitHub code-search page for a bounded query."""
        query = self._validate_search_query(query)
        self._validate_search_page(page=page, per_page=per_page)
        parameters = urlencode({"q": query, "page": page, "per_page": per_page})
        return await self._get_model(
            f"/search/code?{parameters}",
            GitHubCodeSearchResponsePayload,
        )

    async def iter_skill_file_pages(
        self,
        query: str,
        *,
        per_page: int = 100,
        max_pages: int = MAX_CODE_SEARCH_PAGES,
    ) -> AsyncIterator[GitHubResponse[GitHubCodeSearchResponsePayload]]:
        """Yield bounded search pages by following GitHub's validated next links."""
        if not 1 <= max_pages <= MAX_CODE_SEARCH_PAGES:
            raise ValueError(f"max_pages must be in the range 1-{MAX_CODE_SEARCH_PAGES}")

        response = await self.search_skill_files(query, per_page=per_page)
        seen_next_urls: set[str] = set()
        for page_index in range(max_pages):
            yield response
            if response.next_url is None or page_index + 1 == max_pages:
                return
            if response.next_url in seen_next_urls:
                raise GitHubResponseError(
                    "GitHub returned a cyclic pagination link",
                    correlation_id=response.correlation_id,
                    status_code=response.status_code,
                    rate_limit=response.rate_limit,
                )
            seen_next_urls.add(response.next_url)
            response = await self._get_model(
                response.next_url,
                GitHubCodeSearchResponsePayload,
            )

    async def get_file(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
        *,
        etag: str | None = None,
    ) -> GitHubResponse[GitHubFilePayload] | GitHubNotModifiedResponse:
        """Fetch one bounded repository file, optionally using a saved ETag."""
        endpoint = self._contents_endpoint(owner, repository, path, ref)
        etag = self._validate_etag(etag) if etag is not None else None
        correlation_id = uuid4().hex
        response = await self._request(
            endpoint,
            correlation_id=correlation_id,
            etag=etag,
            allow_not_modified=etag is not None,
        )
        rate_limit = GitHubRateLimitSnapshot.from_headers(response.headers)
        response_etag = response.headers.get("etag", etag)
        if response.status_code == 304:
            return GitHubNotModifiedResponse(
                etag=response_etag,
                rate_limit=rate_limit,
                correlation_id=correlation_id,
            )

        self._enforce_response_size(
            response,
            maximum_bytes=MAX_SKILL_FILE_RESPONSE_BYTES,
            correlation_id=correlation_id,
            rate_limit=rate_limit,
        )
        payload = self._validate_model_payload(
            response,
            GitHubFilePayload,
            correlation_id=correlation_id,
            rate_limit=rate_limit,
        )
        if payload.size > MAX_SKILL_FILE_SIZE_BYTES:
            raise GitHubPayloadTooLargeError(
                f"GitHub file exceeds the {MAX_SKILL_FILE_SIZE_BYTES}-byte safety limit",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            )
        try:
            decoded_size = len(payload.decode_content())
        except ValueError:
            raise GitHubPayloadError(
                "GitHub file content was not valid Base64",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            ) from None
        if decoded_size != payload.size:
            raise GitHubPayloadError(
                "GitHub file size did not match its decoded content",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            )

        return GitHubResponse(
            data=payload,
            status_code=response.status_code,
            etag=response_etag,
            rate_limit=rate_limit,
            correlation_id=correlation_id,
        )

    async def list_directory(
        self,
        owner: str,
        repository: str,
        path: str,
        ref: str,
    ) -> GitHubResponse[tuple[GitHubDirectoryEntryPayload, ...]]:
        """Return bounded metadata for one repository directory without recursion."""
        endpoint = self._contents_endpoint(
            owner,
            repository,
            path,
            ref,
            allow_root=True,
        )
        correlation_id = uuid4().hex
        response = await self._request(endpoint, correlation_id=correlation_id)
        rate_limit = GitHubRateLimitSnapshot.from_headers(response.headers)
        self._enforce_response_size(
            response,
            maximum_bytes=MAX_DIRECTORY_RESPONSE_BYTES,
            correlation_id=correlation_id,
            rate_limit=rate_limit,
        )
        raw_payload = self._decode_json_payload(
            response,
            correlation_id=correlation_id,
            rate_limit=rate_limit,
        )
        try:
            entries = _DIRECTORY_ENTRIES_ADAPTER.validate_python(raw_payload)
        except ValidationError:
            raise GitHubPayloadError(
                "GitHub directory response did not match the expected schema",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            ) from None
        if len(entries) > MAX_DIRECTORY_ENTRIES:
            raise GitHubPayloadTooLargeError(
                f"GitHub directory exceeds the {MAX_DIRECTORY_ENTRIES}-entry safety limit",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            )

        return GitHubResponse(
            data=entries,
            status_code=response.status_code,
            etag=response.headers.get("etag"),
            rate_limit=rate_limit,
            correlation_id=correlation_id,
        )

    async def _get_model[PayloadT: BaseModel](
        self,
        endpoint: str,
        payload_type: type[PayloadT],
    ) -> GitHubResponse[PayloadT]:
        correlation_id = uuid4().hex
        response = await self._request(endpoint, correlation_id=correlation_id)
        rate_limit = GitHubRateLimitSnapshot.from_headers(response.headers)
        payload = self._validate_model_payload(
            response,
            payload_type,
            correlation_id=correlation_id,
            rate_limit=rate_limit,
        )

        return GitHubResponse(
            data=payload,
            status_code=response.status_code,
            etag=response.headers.get("etag"),
            rate_limit=rate_limit,
            correlation_id=correlation_id,
            next_url=self._next_link(
                response,
                correlation_id=correlation_id,
                rate_limit=rate_limit,
            ),
        )

    async def _request(
        self,
        endpoint: str,
        *,
        correlation_id: str,
        etag: str | None = None,
        allow_not_modified: bool = False,
    ) -> httpx.Response:
        url = validate_github_api_url(urljoin(f"{GITHUB_API_BASE_URL}/", endpoint.lstrip("/")))
        headers = self._request_headers(etag=etag)

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
            if response.is_success or (allow_not_modified and response.status_code == 304):
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

    def _request_headers(self, *, etag: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": self._authorization,
            "User-Agent": f"SkillScope/{__version__}",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        if etag is not None:
            headers["If-None-Match"] = etag
        return headers

    @staticmethod
    def _validate_search_query(query: str) -> str:
        if query != query.strip() or not query:
            raise ValueError("search query must be non-empty and have no surrounding whitespace")
        if len(query) > MAX_CODE_SEARCH_QUERY_CHARACTERS:
            raise ValueError(
                f"search query must not exceed {MAX_CODE_SEARCH_QUERY_CHARACTERS} characters"
            )
        if any(ord(character) < 32 or ord(character) == 127 for character in query):
            raise ValueError("search query contains a control character")
        return query

    @staticmethod
    def _validate_search_page(*, page: int, per_page: int) -> None:
        if not 1 <= per_page <= 100:
            raise ValueError("per_page must be in the range 1-100")
        if page < 1 or (page - 1) * per_page >= MAX_CODE_SEARCH_RESULTS:
            raise ValueError("page falls outside GitHub's first 1,000 search results")

    @staticmethod
    def _validate_etag(etag: str) -> str:
        if etag != etag.strip() or not etag:
            raise ValueError("ETag must be non-empty and have no surrounding whitespace")
        if len(etag.encode("utf-8")) > MAX_ETAG_BYTES:
            raise ValueError(f"ETag must not exceed {MAX_ETAG_BYTES} bytes")
        if any(ord(character) < 32 or ord(character) == 127 for character in etag):
            raise ValueError("ETag contains a control character")
        return etag

    @staticmethod
    def _contents_endpoint(
        owner: str,
        repository: str,
        path: str,
        ref: str,
        *,
        allow_root: bool = False,
    ) -> str:
        owner = validate_owner(owner)
        repository = validate_repository_name(repository)
        ref = validate_git_ref(ref)
        if not path and allow_root:
            path_suffix = ""
        else:
            path = validate_relative_path(path)
            path_suffix = f"/{quote(path, safe='/')}"
        parameters = urlencode({"ref": ref})
        return f"/repos/{owner}/{repository}/contents{path_suffix}?{parameters}"

    def _validate_model_payload[PayloadT: BaseModel](
        self,
        response: httpx.Response,
        payload_type: type[PayloadT],
        *,
        correlation_id: str,
        rate_limit: GitHubRateLimitSnapshot,
    ) -> PayloadT:
        raw_payload = self._decode_json_payload(
            response,
            correlation_id=correlation_id,
            rate_limit=rate_limit,
        )
        try:
            return payload_type.model_validate(raw_payload)
        except ValidationError:
            raise GitHubPayloadError(
                "GitHub response did not match the expected schema",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            ) from None

    @staticmethod
    def _decode_json_payload(
        response: httpx.Response,
        *,
        correlation_id: str,
        rate_limit: GitHubRateLimitSnapshot,
    ) -> object:
        try:
            return response.json()
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise GitHubPayloadError(
                "GitHub returned malformed JSON",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            ) from None

    @staticmethod
    def _enforce_response_size(
        response: httpx.Response,
        *,
        maximum_bytes: int,
        correlation_id: str,
        rate_limit: GitHubRateLimitSnapshot,
    ) -> None:
        if len(response.content) > maximum_bytes:
            raise GitHubPayloadTooLargeError(
                f"GitHub response exceeds the {maximum_bytes}-byte safety limit",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            )

    @staticmethod
    def _next_link(
        response: httpx.Response,
        *,
        correlation_id: str,
        rate_limit: GitHubRateLimitSnapshot,
    ) -> str | None:
        link_header = response.headers.get("link")
        if link_header is None:
            return None
        try:
            next_link = response.links.get("next")
        except (KeyError, ValueError):
            next_link = None
        if next_link is None:
            if 'rel="next"' in link_header.casefold():
                raise GitHubResponseError(
                    "GitHub returned a malformed pagination link",
                    correlation_id=correlation_id,
                    status_code=response.status_code,
                    rate_limit=rate_limit,
                )
            return None
        next_url = next_link.get("url")
        if not next_url:
            raise GitHubResponseError(
                "GitHub returned a malformed pagination link",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            )
        try:
            return validate_github_api_url(next_url)
        except ValueError:
            raise GitHubResponseError(
                "GitHub returned a pagination link outside the allowlisted API host",
                correlation_id=correlation_id,
                status_code=response.status_code,
                rate_limit=rate_limit,
            ) from None

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
