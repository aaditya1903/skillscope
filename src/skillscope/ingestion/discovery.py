"""Deterministic discovery of public Agent Skills on GitHub."""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from skillscope.ingestion.github_client import GitHubResponse
from skillscope.ingestion.models import (
    GitHubCodeSearchItemPayload,
    GitHubCodeSearchResponsePayload,
)
from skillscope.ingestion.validation import validate_repository_full_name

DEFAULT_SEARCH_MARKERS = ("description", "name")
MAX_DISCOVERY_QUERIES = 20
MAX_DISCOVERY_TARGET = 1_000
MAX_DISCOVERY_PAGES_PER_QUERY = 10

# GitHub returns a permalink whose ref is the commit the search index matched.
_PERMALINK_PATTERN = re.compile(
    r"^https://github\.com/[^/]+/[^/]+/blob/(?P<commit>[0-9a-f]{40})/(?P<path>.+)$"
)


class DiscoveryClient(Protocol):
    """The bounded GitHub operation required by candidate discovery."""

    def iter_skill_file_pages(
        self,
        query: str,
        *,
        per_page: int = 100,
        max_pages: int = MAX_DISCOVERY_PAGES_PER_QUERY,
    ) -> AsyncIterator[GitHubResponse[GitHubCodeSearchResponsePayload]]:
        """Yield validated code-search pages for one exact query."""
        ...


class DiscoveryConflictError(RuntimeError):
    """GitHub returned inconsistent metadata for one candidate in a run."""


@dataclass(frozen=True, slots=True)
class DiscoveryPlan:
    """Checked-in inputs that define one reproducible discovery run."""

    seed_repositories: tuple[str, ...]
    queries: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SkillCandidate:
    """One public ``SKILL.md`` identity discovered through code search."""

    repository_id: int
    repository_full_name: str
    repository_html_url: str
    path: str
    git_blob_sha: str
    html_url: str
    matched_queries: tuple[str, ...]

    @property
    def identity(self) -> str:
        """Return the repository-ID and path deduplication key."""
        return f"{self.repository_id}:{self.path}"

    @property
    def pinned_commit(self) -> str | None:
        """Return the commit the discovery permalink recorded for this file.

        Fetching that commit rather than the default branch keeps a rerun
        reproducible after upstream rewrites the file, and it is already frozen
        evidence because the permalink is stored in the candidate manifest.
        Returns ``None`` when GitHub used a non-permalink form, in which case
        the caller falls back to the repository default branch.
        """

        match = _PERMALINK_PATTERN.fullmatch(self.html_url)
        if match is None or match.group("path") != self.path:
            return None
        return match.group("commit")


@dataclass(frozen=True, slots=True)
class DiscoveryPageBoundary:
    """Stable evidence describing one consumed GitHub result page."""

    query: str
    page_number: int
    item_count: int
    accepted_item_count: int
    total_count: int
    incomplete_results: bool
    has_next: bool
    first_result: str | None
    last_result: str | None


@dataclass(frozen=True, slots=True)
class DiscoveryResult:
    """Deterministically ordered candidates and their discovery evidence."""

    plan: DiscoveryPlan
    target_skills: int
    target_reached: bool
    pages: tuple[DiscoveryPageBoundary, ...]
    candidates: tuple[SkillCandidate, ...]

    @property
    def candidate_count(self) -> int:
        """Return the number of candidates retained for the manifest."""
        return len(self.candidates)


@dataclass(slots=True)
class _CandidateState:
    repository_id: int
    repository_full_name: str
    repository_html_url: str
    path: str
    git_blob_sha: str
    html_url: str
    matched_queries: set[str] = field(default_factory=set)


def normalize_seed_repositories(repositories: Iterable[str]) -> tuple[str, ...]:
    """Validate, deduplicate and sort public ``owner/repository`` identifiers."""
    unique: dict[str, str] = {}
    for raw_repository in repositories:
        repository = raw_repository.strip()
        if not repository:
            continue
        repository = validate_repository_full_name(repository)
        unique.setdefault(repository.casefold(), repository)

    if not unique:
        raise ValueError("at least one seed repository is required")

    return tuple(sorted(unique.values(), key=lambda value: (value.casefold(), value)))


def load_seed_repositories(path: Path) -> tuple[str, ...]:
    """Load identifier-only seed data from a UTF-8 text file."""
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError("seed repository file must be valid UTF-8") from error

    repositories = (line.partition("#")[0].strip() for line in text.splitlines())
    return normalize_seed_repositories(repositories)


def build_discovery_plan(seed_repositories: Iterable[str]) -> DiscoveryPlan:
    """Build stable seed-specific queries followed by bounded broad queries."""
    seeds = normalize_seed_repositories(seed_repositories)
    queries = tuple(
        f"{marker} filename:SKILL.md repo:{repository}"
        for repository in seeds
        for marker in DEFAULT_SEARCH_MARKERS
    ) + tuple(f"{marker} filename:SKILL.md" for marker in DEFAULT_SEARCH_MARKERS)
    if len(queries) > MAX_DISCOVERY_QUERIES:
        raise ValueError(f"discovery plan exceeds the {MAX_DISCOVERY_QUERIES}-query safety limit")
    return DiscoveryPlan(seed_repositories=seeds, queries=queries)


async def discover_skill_candidates(
    client: DiscoveryClient,
    plan: DiscoveryPlan,
    *,
    target_skills: int = 100,
    per_page: int = 100,
    max_pages_per_query: int = MAX_DISCOVERY_PAGES_PER_QUERY,
) -> DiscoveryResult:
    """Execute a bounded plan, deduplicate candidates and return stable output."""
    _validate_discovery_inputs(
        plan,
        target_skills=target_skills,
        per_page=per_page,
        max_pages_per_query=max_pages_per_query,
    )
    query_rank = {query: index for index, query in enumerate(plan.queries)}
    candidates: dict[tuple[int, str], _CandidateState] = {}
    page_boundaries: list[DiscoveryPageBoundary] = []

    for query in plan.queries:
        page_number = 0
        async for response in client.iter_skill_file_pages(
            query,
            per_page=per_page,
            max_pages=max_pages_per_query,
        ):
            page_number += 1
            items = response.data.items
            accepted_item_count = 0
            for item in items:
                if not _is_public_skill_file(item):
                    continue
                accepted_item_count += 1
                _record_candidate(candidates, item, query=query)

            identities = tuple(_result_identity(item) for item in items)
            page_boundaries.append(
                DiscoveryPageBoundary(
                    query=query,
                    page_number=page_number,
                    item_count=len(items),
                    accepted_item_count=accepted_item_count,
                    total_count=response.data.total_count,
                    incomplete_results=response.data.incomplete_results,
                    has_next=response.next_url is not None,
                    first_result=identities[0] if identities else None,
                    last_result=identities[-1] if identities else None,
                )
            )
            if len(candidates) >= target_skills:
                break

        if len(candidates) >= target_skills:
            break

    ordered_candidates = sorted(
        (
            SkillCandidate(
                repository_id=state.repository_id,
                repository_full_name=state.repository_full_name,
                repository_html_url=state.repository_html_url,
                path=state.path,
                git_blob_sha=state.git_blob_sha,
                html_url=state.html_url,
                matched_queries=tuple(sorted(state.matched_queries, key=query_rank.__getitem__)),
            )
            for state in candidates.values()
        ),
        key=lambda candidate: (candidate.repository_full_name, candidate.path),
    )
    target_reached = len(ordered_candidates) >= target_skills

    return DiscoveryResult(
        plan=plan,
        target_skills=target_skills,
        target_reached=target_reached,
        pages=tuple(page_boundaries),
        candidates=tuple(ordered_candidates[:target_skills]),
    )


def _validate_discovery_inputs(
    plan: DiscoveryPlan,
    *,
    target_skills: int,
    per_page: int,
    max_pages_per_query: int,
) -> None:
    if not plan.queries:
        raise ValueError("discovery plan must contain at least one query")
    if len(plan.queries) > MAX_DISCOVERY_QUERIES:
        raise ValueError(f"discovery plan exceeds the {MAX_DISCOVERY_QUERIES}-query safety limit")
    if len(set(plan.queries)) != len(plan.queries):
        raise ValueError("discovery plan contains duplicate queries")
    if any(not query or query != query.strip() for query in plan.queries):
        raise ValueError("discovery queries must be non-empty and trimmed")
    if not 1 <= target_skills <= MAX_DISCOVERY_TARGET:
        raise ValueError(f"target_skills must be in the range 1-{MAX_DISCOVERY_TARGET}")
    if not 1 <= per_page <= 100:
        raise ValueError("per_page must be in the range 1-100")
    if not 1 <= max_pages_per_query <= MAX_DISCOVERY_PAGES_PER_QUERY:
        raise ValueError(
            f"max_pages_per_query must be in the range 1-{MAX_DISCOVERY_PAGES_PER_QUERY}"
        )


def _is_public_skill_file(item: GitHubCodeSearchItemPayload) -> bool:
    return (
        not item.repository.private
        and item.name == "SKILL.md"
        and item.path.rsplit("/", maxsplit=1)[-1] == "SKILL.md"
    )


def _record_candidate(
    candidates: dict[tuple[int, str], _CandidateState],
    item: GitHubCodeSearchItemPayload,
    *,
    query: str,
) -> None:
    key = (item.repository.id, item.path)
    existing = candidates.get(key)
    if existing is None:
        candidates[key] = _CandidateState(
            repository_id=item.repository.id,
            repository_full_name=item.repository.full_name,
            repository_html_url=item.repository.html_url,
            path=item.path,
            git_blob_sha=item.sha,
            html_url=item.html_url,
            matched_queries={query},
        )
        return

    current_metadata = (
        item.repository.full_name,
        item.repository.html_url,
        item.sha,
        item.html_url,
    )
    recorded_metadata = (
        existing.repository_full_name,
        existing.repository_html_url,
        existing.git_blob_sha,
        existing.html_url,
    )
    if current_metadata != recorded_metadata:
        raise DiscoveryConflictError(
            "GitHub returned conflicting metadata for "
            f"repository_id={item.repository.id}, path={item.path}"
        )
    existing.matched_queries.add(query)


def _result_identity(item: GitHubCodeSearchItemPayload) -> str:
    return f"{item.repository.id}:{item.path}"
