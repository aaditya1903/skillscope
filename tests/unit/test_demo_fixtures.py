"""Tests for the token-free demonstration corpus and its local client."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

import pytest

from skillscope.demo import DEMO_REPOSITORY_FULL_NAME, LocalFixtureClient, build_demo_manifest
from skillscope.ingestion.github_client import GitHubNotFoundError

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_manifest_describes_every_committed_fixture_deterministically() -> None:
    first = build_demo_manifest(PROJECT_ROOT)
    second = build_demo_manifest(PROJECT_ROOT)

    assert first.header.candidate_count == len(first.candidates)
    assert first.header.candidate_count >= 10
    assert first == second
    assert all(
        candidate.repository_full_name == DEMO_REPOSITORY_FULL_NAME
        for candidate in first.candidates
    )
    assert all(
        candidate.path.startswith("data/demo/skills/") and candidate.path.endswith("SKILL.md")
        for candidate in first.candidates
    )


def test_manifest_blob_shas_match_git() -> None:
    manifest = build_demo_manifest(PROJECT_ROOT)
    client = LocalFixtureClient(PROJECT_ROOT)

    for candidate in manifest.candidates:
        owner, repository = candidate.repository_full_name.split("/", maxsplit=1)
        response = asyncio.run(
            client.get_file(owner, repository, candidate.path, "main"),
        )
        assert response.data.sha == candidate.git_blob_sha
        assert base64.b64decode(response.data.content)


def test_fixture_client_refuses_paths_outside_the_demonstration_corpus() -> None:
    client = LocalFixtureClient(PROJECT_ROOT)
    owner, repository = DEMO_REPOSITORY_FULL_NAME.split("/", maxsplit=1)

    with pytest.raises(GitHubNotFoundError):
        asyncio.run(client.get_file(owner, repository, "pyproject.toml", "main"))
    with pytest.raises(GitHubNotFoundError):
        asyncio.run(client.get_file(owner, repository, ".env", "main"))


def test_fixture_client_serves_only_the_demonstration_repository() -> None:
    client = LocalFixtureClient(PROJECT_ROOT)

    with pytest.raises(GitHubNotFoundError):
        asyncio.run(client.get_repository("someone", "else"))


def test_fixture_directory_listing_stays_inside_the_skill_directory() -> None:
    client = LocalFixtureClient(PROJECT_ROOT)
    owner, repository = DEMO_REPOSITORY_FULL_NAME.split("/", maxsplit=1)

    response = asyncio.run(
        client.list_directory(
            owner,
            repository,
            "data/demo/skills/spreadsheet-report",
            "main",
        )
    )

    paths = {entry.path for entry in response.data}
    assert "data/demo/skills/spreadsheet-report/SKILL.md" in paths
    assert all(path.startswith("data/demo/skills/spreadsheet-report/") for path in paths)
