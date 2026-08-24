"""Tests for deterministic, network-free GitHub candidate discovery."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest

from skillscope.ingestion.discovery import (
    DiscoveryConflictError,
    DiscoveryPlan,
    build_discovery_plan,
    discover_skill_candidates,
    load_seed_repositories,
    normalize_seed_repositories,
)
from skillscope.ingestion.github_client import GitHubResponse
from skillscope.ingestion.models import (
    GitHubCodeSearchItemPayload,
    GitHubCodeSearchResponsePayload,
)


class FakeDiscoveryClient:
    """Yield prevalidated pages without making network calls."""

    def __init__(
        self,
        pages_by_query: dict[
            str,
            tuple[GitHubResponse[GitHubCodeSearchResponsePayload], ...],
        ],
    ) -> None:
        self.pages_by_query = pages_by_query
        self.calls: list[tuple[str, int, int]] = []

    async def iter_skill_file_pages(
        self,
        query: str,
        *,
        per_page: int = 100,
        max_pages: int = 10,
    ) -> AsyncIterator[GitHubResponse[GitHubCodeSearchResponsePayload]]:
        self.calls.append((query, per_page, max_pages))
        for response in self.pages_by_query.get(query, ())[:max_pages]:
            yield response


def make_item(
    repository_id: int,
    repository_full_name: str,
    path: str,
    *,
    sha: str = "a" * 40,
    private: bool = False,
) -> GitHubCodeSearchItemPayload:
    owner, repository = repository_full_name.split("/", maxsplit=1)
    name = path.rsplit("/", maxsplit=1)[-1]
    return GitHubCodeSearchItemPayload.model_validate(
        {
            "name": name,
            "path": path,
            "sha": sha,
            "url": (f"https://api.github.com/repositories/{repository_id}/contents/{path}"),
            "git_url": (f"https://api.github.com/repositories/{repository_id}/git/blobs/{sha}"),
            "html_url": (f"https://github.com/{repository_full_name}/blob/main/{path}"),
            "repository": {
                "id": repository_id,
                "name": repository,
                "full_name": repository_full_name,
                "private": private,
                "html_url": f"https://github.com/{repository_full_name}",
                "owner": {
                    "login": owner,
                    "id": repository_id + 10_000,
                    "html_url": f"https://github.com/{owner}",
                },
            },
        }
    )


def make_page(
    *items: GitHubCodeSearchItemPayload,
    total_count: int | None = None,
    incomplete_results: bool = False,
    next_url: str | None = None,
) -> GitHubResponse[GitHubCodeSearchResponsePayload]:
    payload = GitHubCodeSearchResponsePayload(
        total_count=len(items) if total_count is None else total_count,
        incomplete_results=incomplete_results,
        items=items,
    )
    return cast(
        GitHubResponse[GitHubCodeSearchResponsePayload],
        SimpleNamespace(data=payload, next_url=next_url),
    )


def test_normalize_seed_repositories_deduplicates_case_insensitively() -> None:
    assert normalize_seed_repositories(
        [" zeta/tools ", "Anthropics/skills", "anthropics/SKILLS"]
    ) == ("Anthropics/skills", "zeta/tools")


def test_normalize_seed_repositories_rejects_an_empty_collection() -> None:
    with pytest.raises(ValueError, match="at least one seed"):
        normalize_seed_repositories(["", "  "])


def test_load_seed_repositories_accepts_comments_and_blank_lines(
    tmp_path: Path,
) -> None:
    seed_path = tmp_path / "repositories.txt"
    seed_path.write_text(
        "# Known-good public source\n\nanthropics/skills  # official\n",
        encoding="utf-8",
    )

    assert load_seed_repositories(seed_path) == ("anthropics/skills",)


def test_build_discovery_plan_puts_seed_queries_before_broad_queries() -> None:
    plan = build_discovery_plan(["anthropics/skills"])

    assert plan.queries == (
        "description filename:SKILL.md repo:anthropics/skills",
        "name filename:SKILL.md repo:anthropics/skills",
        "description filename:SKILL.md",
        "name filename:SKILL.md",
    )


@pytest.mark.asyncio
async def test_discovery_filters_deduplicates_and_sorts_candidates() -> None:
    plan = build_discovery_plan(["anthropics/skills"])
    seed_query, _, broad_query, _ = plan.queries
    duplicate = make_item(10, "anthropics/skills", "skills/xlsx/SKILL.md")
    client = FakeDiscoveryClient(
        {
            seed_query: (
                make_page(
                    make_item(10, "anthropics/skills", "skills/zeta/SKILL.md"),
                    duplicate,
                    make_item(
                        11,
                        "private/tools",
                        "hidden/SKILL.md",
                        private=True,
                    ),
                    make_item(12, "other/tools", "README.md"),
                ),
            ),
            broad_query: (
                make_page(
                    duplicate,
                    make_item(2, "alpha/tools", "skills/a/SKILL.md"),
                ),
            ),
        }
    )

    result = await discover_skill_candidates(client, plan, target_skills=10)

    assert [candidate.identity for candidate in result.candidates] == [
        "2:skills/a/SKILL.md",
        "10:skills/xlsx/SKILL.md",
        "10:skills/zeta/SKILL.md",
    ]
    assert result.candidates[1].matched_queries == (seed_query, broad_query)
    assert result.target_reached is False
    assert result.candidate_count == 3


@pytest.mark.asyncio
async def test_discovery_records_page_boundaries_and_stops_at_target() -> None:
    plan = build_discovery_plan(["anthropics/skills"])
    first_query = plan.queries[0]
    client = FakeDiscoveryClient(
        {
            first_query: (
                make_page(
                    make_item(3, "zeta/tools", "z/SKILL.md"),
                    make_item(1, "alpha/tools", "a/SKILL.md"),
                    make_item(2, "beta/tools", "b/SKILL.md"),
                    total_count=20,
                    incomplete_results=True,
                    next_url="https://api.github.com/search/code?page=2",
                ),
            )
        }
    )

    result = await discover_skill_candidates(client, plan, target_skills=2)

    assert [candidate.repository_full_name for candidate in result.candidates] == [
        "alpha/tools",
        "beta/tools",
    ]
    assert result.target_reached is True
    assert client.calls == [(first_query, 100, 10)]
    assert result.pages[0].item_count == 3
    assert result.pages[0].accepted_item_count == 3
    assert result.pages[0].total_count == 20
    assert result.pages[0].incomplete_results is True
    assert result.pages[0].has_next is True
    assert result.pages[0].first_result == "3:z/SKILL.md"
    assert result.pages[0].last_result == "2:b/SKILL.md"


@pytest.mark.asyncio
async def test_discovery_rejects_conflicting_candidate_metadata() -> None:
    plan = build_discovery_plan(["anthropics/skills"])
    first_query, second_query = plan.queries[:2]
    client = FakeDiscoveryClient(
        {
            first_query: (make_page(make_item(10, "anthropics/skills", "skills/x/SKILL.md")),),
            second_query: (
                make_page(
                    make_item(
                        10,
                        "anthropics/skills",
                        "skills/x/SKILL.md",
                        sha="b" * 40,
                    )
                ),
            ),
        }
    )

    with pytest.raises(DiscoveryConflictError, match="conflicting metadata"):
        await discover_skill_candidates(client, plan, target_skills=10)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("keyword_arguments", "message"),
    [
        ({"target_skills": 0}, "target_skills"),
        ({"per_page": 101}, "per_page"),
        ({"max_pages_per_query": 11}, "max_pages_per_query"),
    ],
)
async def test_discovery_rejects_unbounded_inputs(
    keyword_arguments: dict[str, int],
    message: str,
) -> None:
    client = FakeDiscoveryClient({})
    plan = DiscoveryPlan(
        seed_repositories=("anthropics/skills",),
        queries=("description filename:SKILL.md",),
    )

    with pytest.raises(ValueError, match=message):
        await discover_skill_candidates(client, plan, **keyword_arguments)
