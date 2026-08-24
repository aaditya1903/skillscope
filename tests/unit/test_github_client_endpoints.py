"""Mocked tests for GitHub search, contents, pagination, and ETags."""

from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest

from skillscope.ingestion.github_client import (
    MAX_DIRECTORY_ENTRIES,
    MAX_SKILL_FILE_RESPONSE_BYTES,
    MAX_SKILL_FILE_SIZE_BYTES,
    GitHubClient,
    GitHubNotModifiedResponse,
    GitHubPayloadError,
    GitHubPayloadTooLargeError,
    GitHubResponse,
    GitHubResponseError,
)

TOKEN = "not-a-real-token-sensitive-marker"
SHA = "9da54804cc8c938586f89363c8da3b3a6e2a563d"
QUERY = "description filename:SKILL.md repo:anthropics/skills"

OWNER_PAYLOAD = {
    "login": "anthropics",
    "id": 1,
    "html_url": "https://github.com/anthropics",
}
REPOSITORY_SUMMARY_PAYLOAD = {
    "id": 1_061_953_414,
    "name": "skills",
    "full_name": "anthropics/skills",
    "owner": OWNER_PAYLOAD,
    "private": False,
    "html_url": "https://github.com/anthropics/skills",
}


def _search_payload(path: str = "skills/xlsx/SKILL.md") -> dict[str, object]:
    return {
        "total_count": 2,
        "incomplete_results": False,
        "items": [
            {
                "name": "SKILL.md",
                "path": path,
                "sha": SHA,
                "url": f"https://api.github.com/repos/anthropics/skills/contents/{path}",
                "git_url": f"https://api.github.com/repos/anthropics/skills/git/blobs/{SHA}",
                "html_url": f"https://github.com/anthropics/skills/blob/main/{path}",
                "repository": REPOSITORY_SUMMARY_PAYLOAD,
            }
        ],
    }


def _file_payload(
    *,
    size: int = 4,
    encoding: str = "base64",
    content: str | None = "LS0tCg==",
) -> dict[str, object]:
    path = "skills/xlsx/SKILL.md"
    return {
        "type": "file",
        "name": "SKILL.md",
        "path": path,
        "sha": SHA,
        "size": size,
        "encoding": encoding,
        "content": content,
        "url": f"https://api.github.com/repos/anthropics/skills/contents/{path}",
        "git_url": f"https://api.github.com/repos/anthropics/skills/git/blobs/{SHA}",
        "html_url": f"https://github.com/anthropics/skills/blob/main/{path}",
    }


def _directory_entry(
    *,
    name: str = "SKILL.md",
    path: str = "skills/xlsx/SKILL.md",
    entry_type: str = "file",
) -> dict[str, object]:
    return {
        "type": entry_type,
        "name": name,
        "path": path,
        "sha": SHA,
        "size": 4,
        "url": f"https://api.github.com/repos/anthropics/skills/contents/{path}",
        "git_url": f"https://api.github.com/repos/anthropics/skills/git/blobs/{SHA}",
        "html_url": f"https://github.com/anthropics/skills/blob/main/{path}",
    }


def _mock_client(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[GitHubClient, httpx.AsyncClient]:
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        trust_env=False,
    )
    return GitHubClient(TOKEN, client=http_client), http_client


@pytest.mark.asyncio
async def test_search_page_encodes_query_and_exposes_validated_next_link() -> None:
    requests: list[httpx.Request] = []
    next_url = (
        "https://api.github.com/search/code?"
        "q=description%20filename%3ASKILL.md%20repo%3Aanthropics%2Fskills&page=3&per_page=50"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_search_payload(),
            headers={"Link": f'<{next_url}>; rel="next"'},
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        result = await client.search_skill_files(QUERY, page=2, per_page=50)

    assert requests[0].url.path == "/search/code"
    assert requests[0].url.params["q"] == QUERY
    assert requests[0].url.params["page"] == "2"
    assert requests[0].url.params["per_page"] == "50"
    assert result.data.items[0].path == "skills/xlsx/SKILL.md"
    assert result.next_url == next_url


@pytest.mark.asyncio
async def test_page_iterator_follows_github_next_link_until_it_is_absent() -> None:
    requested_pages: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = request.url.params["page"]
        requested_pages.append(page)
        headers = {}
        if page == "1":
            headers["Link"] = (
                "<https://api.github.com/search/code?per_page=1&page=2&q=description%20"
                'filename%3ASKILL.md%20repo%3Aanthropics%2Fskills>; rel="next"'
            )
        path = "skills/xlsx/SKILL.md" if page == "1" else "skills/pdf/SKILL.md"
        return httpx.Response(
            200,
            json=_search_payload(path),
            headers=headers,
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        pages = [
            page
            async for page in client.iter_skill_file_pages(
                QUERY,
                per_page=1,
            )
        ]

    assert requested_pages == ["1", "2"]
    assert [page.data.items[0].path for page in pages] == [
        "skills/xlsx/SKILL.md",
        "skills/pdf/SKILL.md",
    ]


@pytest.mark.asyncio
async def test_page_iterator_respects_caller_page_bound() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            json=_search_payload(),
            headers={
                "Link": ('<https://api.github.com/search/code?q=x&page=2&per_page=100>; rel="next"')
            },
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        pages = [page async for page in client.iter_skill_file_pages(QUERY, max_pages=1)]

    assert len(pages) == 1
    assert request_count == 1


@pytest.mark.asyncio
async def test_unsafe_pagination_link_is_rejected_without_following_it() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        request_count += 1
        return httpx.Response(
            200,
            json=_search_payload(),
            headers={"Link": '<https://evil.example/collect>; rel="next"'},
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(GitHubResponseError, match="allowlisted API host"):
            await client.search_skill_files(QUERY)

    assert request_count == 1


@pytest.mark.asyncio
async def test_cyclic_pagination_link_is_rejected() -> None:
    parameters = httpx.QueryParams({"q": QUERY, "page": 2, "per_page": 100})
    page_two_url = f"https://api.github.com/search/code?{parameters}"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_search_payload(),
            headers={"Link": f'<{page_two_url}>; rel="next"'},
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(GitHubResponseError, match="cyclic"):
            _ = [page async for page in client.iter_skill_file_pages(QUERY)]


@pytest.mark.parametrize(
    ("query", "page", "per_page"),
    [
        ("", 1, 100),
        (" surrounded ", 1, 100),
        ("x" * 257, 1, 100),
        ("valid", 0, 100),
        ("valid", 1, 0),
        ("valid", 1, 101),
        ("valid", 11, 100),
    ],
)
@pytest.mark.asyncio
async def test_search_rejects_invalid_bounds_before_request(
    query: str,
    page: int,
    per_page: int,
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid search parameters reached the network")

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(ValueError):
            await client.search_skill_files(query, page=page, per_page=per_page)


@pytest.mark.asyncio
async def test_file_fetch_validates_identifiers_and_returns_typed_payload() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=_file_payload(),
            headers={"ETag": '"file-etag"'},
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        result = await client.get_file(
            "anthropics",
            "skills",
            "skills/xlsx/SKILL.md",
            "feature/docs",
        )

    assert isinstance(result, GitHubResponse)
    assert requests[0].url.path == "/repos/anthropics/skills/contents/skills/xlsx/SKILL.md"
    assert requests[0].url.params["ref"] == "feature/docs"
    assert "if-none-match" not in requests[0].headers
    assert result.data.path == "skills/xlsx/SKILL.md"
    assert result.etag == '"file-etag"'


@pytest.mark.asyncio
async def test_conditional_file_fetch_returns_distinct_not_modified_result() -> None:
    request_etags: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_etags.append(request.headers["if-none-match"])
        return httpx.Response(304, headers={"ETag": '"file-etag"'}, request=request)

    client, http_client = _mock_client(handler)
    async with http_client:
        result = await client.get_file(
            "anthropics",
            "skills",
            "skills/xlsx/SKILL.md",
            "main",
            etag='"file-etag"',
        )

    assert isinstance(result, GitHubNotModifiedResponse)
    assert result.status_code == 304
    assert result.etag == '"file-etag"'
    assert request_etags == ['"file-etag"']


@pytest.mark.asyncio
async def test_file_size_is_rejected_before_content_is_used() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_file_payload(size=MAX_SKILL_FILE_SIZE_BYTES + 1),
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(GitHubPayloadTooLargeError, match="file exceeds"):
            await client.get_file(
                "anthropics",
                "skills",
                "skills/xlsx/SKILL.md",
                "main",
            )


@pytest.mark.asyncio
async def test_oversized_file_response_is_rejected_before_json_parsing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * (MAX_SKILL_FILE_RESPONSE_BYTES + 1),
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(GitHubPayloadTooLargeError, match="response exceeds"):
            await client.get_file(
                "anthropics",
                "skills",
                "skills/xlsx/SKILL.md",
                "main",
            )


@pytest.mark.asyncio
async def test_file_without_base64_content_is_rejected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_file_payload(encoding="none", content=None),
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(GitHubPayloadError, match="not valid Base64"):
            await client.get_file(
                "anthropics",
                "skills",
                "skills/xlsx/SKILL.md",
                "main",
            )


@pytest.mark.parametrize(
    ("size", "content", "message"),
    [
        (4, "not-base64!", "not valid Base64"),
        (3, "LS0tCg==", "size did not match"),
    ],
)
@pytest.mark.asyncio
async def test_file_content_and_declared_size_must_agree(
    size: int,
    content: str,
    message: str,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_file_payload(size=size, content=content),
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(GitHubPayloadError, match=message):
            await client.get_file(
                "anthropics",
                "skills",
                "skills/xlsx/SKILL.md",
                "main",
            )


@pytest.mark.parametrize("etag", ["", " padded ", '"safe"\nInjected: yes', "x" * 513])
@pytest.mark.asyncio
async def test_invalid_etag_is_rejected_before_request(etag: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("invalid ETag reached the network")

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(ValueError):
            await client.get_file(
                "anthropics",
                "skills",
                "skills/xlsx/SKILL.md",
                "main",
                etag=etag,
            )


@pytest.mark.asyncio
async def test_directory_listing_supports_root_without_recursive_fetching() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[_directory_entry()],
            request=request,
        )

    client, http_client = _mock_client(handler)
    async with http_client:
        result = await client.list_directory("anthropics", "skills", "", "main")

    assert requests[0].url.path == "/repos/anthropics/skills/contents"
    assert requests[0].url.params["ref"] == "main"
    assert isinstance(result.data, tuple)
    assert result.data[0].name == "SKILL.md"


@pytest.mark.asyncio
async def test_directory_entry_bound_is_enforced() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        entries = [_directory_entry()] * (MAX_DIRECTORY_ENTRIES + 1)
        return httpx.Response(200, json=entries, request=request)

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(GitHubPayloadTooLargeError, match="directory exceeds"):
            await client.list_directory("anthropics", "skills", "skills/xlsx", "main")


@pytest.mark.asyncio
async def test_contents_paths_reject_traversal_before_request() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise AssertionError("unsafe path reached the network")

    client, http_client = _mock_client(handler)
    async with http_client:
        with pytest.raises(ValueError):
            await client.get_file("anthropics", "skills", "../SKILL.md", "main")
        with pytest.raises(ValueError):
            await client.list_directory("anthropics", "skills", "../", "main")
