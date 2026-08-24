"""Tests for versioned and deterministic discovery manifests."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from skillscope.ingestion.discovery import (
    DiscoveryPageBoundary,
    DiscoveryPlan,
    DiscoveryResult,
    SkillCandidate,
)
from skillscope.ingestion.manifest import (
    CandidateManifest,
    ManifestValidationError,
    build_candidate_manifest,
    read_candidate_manifest,
    serialize_candidate_manifest,
    write_candidate_manifest,
)

GIT_COMMIT = "d" * 40
GENERATED_AT = datetime(2026, 8, 24, 12, 30, tzinfo=UTC)
SEED_QUERY = "description filename:SKILL.md repo:anthropics/skills"
BROAD_QUERY = "description filename:SKILL.md"


def make_discovery_result() -> DiscoveryResult:
    """Return a small sorted result containing identifiers but no file bodies."""
    return DiscoveryResult(
        plan=DiscoveryPlan(
            seed_repositories=("anthropics/skills",),
            queries=(SEED_QUERY, BROAD_QUERY),
        ),
        target_skills=100,
        target_reached=False,
        pages=(
            DiscoveryPageBoundary(
                query=SEED_QUERY,
                page_number=1,
                item_count=2,
                accepted_item_count=2,
                total_count=20,
                incomplete_results=False,
                has_next=True,
                first_result="10:skills/xlsx/SKILL.md",
                last_result="10:skills/zeta/SKILL.md",
            ),
            DiscoveryPageBoundary(
                query=BROAD_QUERY,
                page_number=1,
                item_count=1,
                accepted_item_count=1,
                total_count=200,
                incomplete_results=True,
                has_next=True,
                first_result="2:skills/a/SKILL.md",
                last_result="2:skills/a/SKILL.md",
            ),
        ),
        candidates=(
            SkillCandidate(
                repository_id=2,
                repository_full_name="alpha/tools",
                repository_html_url="https://github.com/alpha/tools",
                path="skills/a/SKILL.md",
                git_blob_sha="a" * 40,
                html_url=("https://github.com/alpha/tools/blob/main/skills/a/SKILL.md"),
                matched_queries=(BROAD_QUERY,),
            ),
            SkillCandidate(
                repository_id=10,
                repository_full_name="anthropics/skills",
                repository_html_url="https://github.com/anthropics/skills",
                path="skills/xlsx/SKILL.md",
                git_blob_sha="b" * 40,
                html_url=("https://github.com/anthropics/skills/blob/main/skills/xlsx/SKILL.md"),
                matched_queries=(SEED_QUERY, BROAD_QUERY),
            ),
        ),
    )


def make_manifest() -> CandidateManifest:
    return build_candidate_manifest(
        make_discovery_result(),
        generated_at=GENERATED_AT,
        git_commit=GIT_COMMIT,
    )


def write_lines(path: Path, lines: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(line, sort_keys=True, separators=(",", ":")) + "\n" for line in lines),
        encoding="utf-8",
    )


def test_build_manifest_records_exact_run_metadata() -> None:
    manifest = make_manifest()

    assert manifest.header.schema_version == 1
    assert manifest.header.generated_at == GENERATED_AT
    assert manifest.header.git_commit == GIT_COMMIT
    assert manifest.header.seed_repositories == ("anthropics/skills",)
    assert manifest.header.queries == (SEED_QUERY, BROAD_QUERY)
    assert manifest.header.page_count == 2
    assert manifest.header.candidate_count == 2


def test_serialization_is_canonical_and_body_free() -> None:
    manifest = make_manifest()

    first = serialize_candidate_manifest(manifest)
    second = serialize_candidate_manifest(manifest)

    assert first == second
    assert first.endswith(b"\n")
    assert b'"record_type":"manifest"' in first
    assert b'"record_type":"page"' in first
    assert b'"record_type":"candidate"' in first
    assert b'"content"' not in first
    assert b'"body"' not in first
    assert b'"token"' not in first


def test_serialization_orders_header_pages_then_candidates() -> None:
    records = [
        json.loads(line) for line in serialize_candidate_manifest(make_manifest()).splitlines()
    ]

    assert [record["record_type"] for record in records] == [
        "manifest",
        "page",
        "page",
        "candidate",
        "candidate",
    ]


def test_write_and_read_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "candidates.jsonl"
    manifest = make_manifest()

    write_candidate_manifest(path, manifest)

    assert read_candidate_manifest(path) == manifest
    assert not list(path.parent.glob(".candidates.jsonl.*.tmp"))


def test_atomic_failure_preserves_the_previous_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "candidates.jsonl"
    previous = b"previous manifest\n"
    path.write_bytes(previous)

    def fail_replace(source: Path, destination: Path) -> None:
        del source, destination
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        write_candidate_manifest(path, make_manifest())

    assert path.read_bytes() == previous
    assert not list(tmp_path.glob(".candidates.jsonl.*.tmp"))


def test_writer_requires_a_jsonl_extension(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match=r"end with \.jsonl"):
        write_candidate_manifest(tmp_path / "candidates.json", make_manifest())


def test_builder_rejects_a_naive_timestamp() -> None:
    with pytest.raises(ManifestValidationError, match="timezone"):
        build_candidate_manifest(
            make_discovery_result(),
            generated_at=datetime(2026, 8, 24, 12, 30),
            git_commit=GIT_COMMIT,
        )


def test_builder_rejects_an_invalid_git_commit() -> None:
    with pytest.raises(ManifestValidationError, match="valid manifest"):
        build_candidate_manifest(
            make_discovery_result(),
            generated_at=GENERATED_AT,
            git_commit="not-a-commit",
        )


@pytest.mark.parametrize(
    "contents",
    [
        b"",
        b"{}",
        b"not-json\n",
        b"{}\n\n",
    ],
)
def test_reader_rejects_empty_noncanonical_or_invalid_jsonl(
    tmp_path: Path,
    contents: bytes,
) -> None:
    path = tmp_path / "candidates.jsonl"
    path.write_bytes(contents)

    with pytest.raises(ManifestValidationError):
        read_candidate_manifest(path)


def test_reader_rejects_unknown_fields(tmp_path: Path) -> None:
    serialized = serialize_candidate_manifest(make_manifest())
    records = [json.loads(line) for line in serialized.splitlines()]
    records[0]["unexpected"] = True
    path = tmp_path / "candidates.jsonl"
    write_lines(path, records)

    with pytest.raises(ManifestValidationError, match="invalid record"):
        read_candidate_manifest(path)


def test_reader_rejects_count_mismatches(tmp_path: Path) -> None:
    records = [
        json.loads(line) for line in serialize_candidate_manifest(make_manifest()).splitlines()
    ]
    records[0]["candidate_count"] = 3
    path = tmp_path / "candidates.jsonl"
    write_lines(path, records)

    with pytest.raises(ManifestValidationError, match="candidate_count"):
        read_candidate_manifest(path)


def test_reader_rejects_unsorted_candidates(tmp_path: Path) -> None:
    records = [
        json.loads(line) for line in serialize_candidate_manifest(make_manifest()).splitlines()
    ]
    records[-2], records[-1] = records[-1], records[-2]
    path = tmp_path / "candidates.jsonl"
    write_lines(path, records)

    with pytest.raises(ManifestValidationError, match="sorted"):
        read_candidate_manifest(path)


def test_reader_rejects_pages_after_candidates(tmp_path: Path) -> None:
    records = [
        json.loads(line) for line in serialize_candidate_manifest(make_manifest()).splitlines()
    ]
    records[2], records[3] = records[3], records[2]
    path = tmp_path / "candidates.jsonl"
    write_lines(path, records)

    with pytest.raises(ManifestValidationError, match="after candidate"):
        read_candidate_manifest(path)
