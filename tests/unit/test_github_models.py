"""Tests for typed GitHub payloads and conservative request validation."""

from datetime import UTC, timedelta

import pytest
from pydantic import ValidationError

from skillscope.ingestion.models import (
    GitHubCodeSearchResponsePayload,
    GitHubDirectoryEntryPayload,
    GitHubFilePayload,
    GitHubRateLimitResponsePayload,
    GitHubRepositoryPayload,
)
from skillscope.ingestion.validation import (
    validate_git_ref,
    validate_github_api_url,
    validate_owner,
    validate_relative_path,
    validate_repository_name,
)

OWNER = {
    "login": "anthropics",
    "id": 1,
    "html_url": "https://github.com/anthropics",
}
REPOSITORY_SUMMARY = {
    "id": 1_061_953_414,
    "name": "skills",
    "full_name": "anthropics/skills",
    "owner": OWNER,
    "private": False,
    "html_url": "https://github.com/anthropics/skills",
}
SHA = "9da54804cc8c938586f89363c8da3b3a6e2a563d"


def test_code_search_response_parses_required_fields_and_ignores_extras() -> None:
    payload = GitHubCodeSearchResponsePayload.model_validate(
        {
            "total_count": 20,
            "incomplete_results": False,
            "unexpected": "ignored",
            "items": [
                {
                    "name": "SKILL.md",
                    "path": "skills/xlsx/SKILL.md",
                    "sha": SHA,
                    "url": (
                        "https://api.github.com/repositories/1061953414/contents/"
                        "skills/xlsx/SKILL.md?ref=main"
                    ),
                    "git_url": f"https://api.github.com/repos/anthropics/skills/git/blobs/{SHA}",
                    "html_url": "https://github.com/anthropics/skills/blob/main/skills/xlsx/SKILL.md",
                    "repository": REPOSITORY_SUMMARY,
                }
            ],
        }
    )

    assert payload.total_count == 20
    assert not payload.incomplete_results
    assert payload.items[0].repository.full_name == "anthropics/skills"
    assert payload.items[0].path == "skills/xlsx/SKILL.md"


def test_repository_payload_accepts_missing_detected_license() -> None:
    payload = GitHubRepositoryPayload.model_validate(
        {
            **REPOSITORY_SUMMARY,
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
    )

    assert payload.license is None
    assert payload.pushed_at is not None
    assert payload.pushed_at.utcoffset() == timedelta(0)


def test_file_and_directory_payloads_preserve_metadata_only() -> None:
    file_payload = GitHubFilePayload.model_validate(
        {
            "type": "file",
            "name": "SKILL.md",
            "path": "skills/xlsx/SKILL.md",
            "sha": SHA,
            "size": 8_598,
            "encoding": "base64",
            "content": "LS0tCg==",
            "url": "https://api.github.com/repos/anthropics/skills/contents/skills/xlsx/SKILL.md",
            "git_url": f"https://api.github.com/repos/anthropics/skills/git/blobs/{SHA}",
            "html_url": "https://github.com/anthropics/skills/blob/main/skills/xlsx/SKILL.md",
        }
    )
    directory_payload = GitHubDirectoryEntryPayload.model_validate(
        {
            "type": "dir",
            "name": "scripts",
            "path": "skills/xlsx/scripts",
            "sha": SHA,
            "size": 0,
            "url": "https://api.github.com/repos/anthropics/skills/contents/skills/xlsx/scripts",
            "git_url": f"https://api.github.com/repos/anthropics/skills/git/trees/{SHA}",
            "html_url": "https://github.com/anthropics/skills/tree/main/skills/xlsx/scripts",
        }
    )

    assert file_payload.encoding == "base64"
    assert directory_payload.type == "dir"
    assert directory_payload.size == 0


def test_rate_limit_resources_remain_distinct() -> None:
    payload = GitHubRateLimitResponsePayload.model_validate(
        {
            "resources": {
                "core": {"limit": 5_000, "used": 0, "remaining": 5_000, "reset": 1_787_517_225},
                "search": {"limit": 30, "used": 0, "remaining": 30, "reset": 1_787_513_685},
                "code_search": {"limit": 10, "used": 1, "remaining": 9, "reset": 1_787_513_685},
            }
        }
    )

    assert payload.resources.core.limit == 5_000
    assert payload.resources.code_search.limit == 10
    assert payload.resources.code_search.reset_at.tzinfo is UTC


@pytest.mark.parametrize(
    "path",
    [
        "../SKILL.md",
        "/skills/xlsx/SKILL.md",
        "skills\\xlsx\\SKILL.md",
        "skills/%2e%2e/SKILL.md",
        "skills//SKILL.md",
    ],
)
def test_relative_path_rejects_traversal_and_ambiguous_encodings(path: str) -> None:
    with pytest.raises(ValueError):
        validate_relative_path(path)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.github.com/search/code",
        "https://api.github.com.evil.example/search/code",
        "https://user@api.github.com/search/code",
        "https://api.github.com:443/search/code",
        "https://api.github.com/repos/owner/repo/../secret",
    ],
)
def test_api_url_requires_exact_allowlisted_host(url: str) -> None:
    with pytest.raises(ValueError):
        validate_github_api_url(url)


@pytest.mark.parametrize("owner", ["-owner", "owner-", "owner_name", "owner--name"])
def test_owner_validation_is_conservative(owner: str) -> None:
    with pytest.raises(ValueError):
        validate_owner(owner)


def test_repository_name_accepts_dot_prefixed_public_repository() -> None:
    assert validate_repository_name(".github") == ".github"


@pytest.mark.parametrize("repository", [".", "repo..name", "repo.", "repo/name"])
def test_repository_name_validation_is_conservative(repository: str) -> None:
    with pytest.raises(ValueError):
        validate_repository_name(repository)


@pytest.mark.parametrize("ref", ["../main", "refs//heads/main", "main.lock", "main~1"])
def test_git_ref_validation_rejects_ambiguous_values(ref: str) -> None:
    with pytest.raises(ValueError):
        validate_git_ref(ref)


def test_payload_rejects_inconsistent_repository_identity() -> None:
    with pytest.raises(ValidationError, match="full_name"):
        GitHubCodeSearchResponsePayload.model_validate(
            {
                "total_count": 1,
                "incomplete_results": False,
                "items": [
                    {
                        "name": "SKILL.md",
                        "path": "SKILL.md",
                        "sha": SHA,
                        "url": "https://api.github.com/repos/anthropics/skills/contents/SKILL.md",
                        "git_url": f"https://api.github.com/repos/anthropics/skills/git/blobs/{SHA}",
                        "html_url": "https://github.com/anthropics/skills/blob/main/SKILL.md",
                        "repository": {
                            **REPOSITORY_SUMMARY,
                            "full_name": "someone-else/skills",
                        },
                    }
                ],
            }
        )
