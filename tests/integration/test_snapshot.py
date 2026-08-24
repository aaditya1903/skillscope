"""PostgreSQL reconciliation coverage for frozen dataset snapshots."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from skillscope.db.enums import (
    IngestionItemStatus,
    IngestionRunStatus,
    LicenseStatus,
    ValidationStatus,
)
from skillscope.db.models import IngestionRun, IngestionRunItem, Repository, Skill
from skillscope.ingestion.manifest import (
    CandidateManifest,
    CandidateManifestCandidate,
    CandidateManifestHeader,
)
from skillscope.ingestion.snapshot import build_dataset_snapshot

pytestmark = pytest.mark.integration


def test_snapshot_reconciles_candidates_run_items_and_current_skills(
    db_session: Session,
) -> None:
    repository = Repository(
        github_repository_id=7_001,
        owner="skillscope-tests",
        name="snapshot",
        full_name="skillscope-tests/snapshot",
        html_url="https://github.com/skillscope-tests/snapshot",
        default_branch="main",
        description="Synthetic snapshot integration fixture.",
        license_spdx_id="MIT",
        license_name="MIT License",
        license_status=LicenseStatus.PERMISSIVE,
        pushed_at=None,
        etag='"snapshot"',
    )
    skill = Skill(
        repository=repository,
        path="skills/alpha/SKILL.md",
        html_url=("https://github.com/skillscope-tests/snapshot/blob/main/skills/alpha/SKILL.md"),
        raw_url=None,
        git_blob_sha="1" * 40,
        content_sha256="a" * 64,
        name="alpha",
        description="Synthetic valid snapshot skill.",
        declared_license="MIT",
        compatibility=None,
        allowed_tools=[],
        metadata_json={},
        extension_fields_json={},
        body_text="# Synthetic\n",
        search_text="alpha synthetic",
        safe_snippet="Synthetic valid snapshot skill.",
        embedding=None,
        validation_status=ValidationStatus.VALID,
        validation_messages_json=[],
        indexed_at=None,
    )
    run = IngestionRun(
        status=IngestionRunStatus.COMPLETED,
        completed_at=datetime.now(UTC),
        discovery_queries_json=["description filename:SKILL.md"],
        config_json={},
        git_commit_sha="c" * 40,
        discovered_count=2,
        fetched_count=2,
        unchanged_count=0,
        parsed_count=2,
        invalid_count=1,
        error_count=0,
        manifest_path="data/manifests/candidates.jsonl",
    )
    db_session.add_all([repository, skill, run])
    db_session.flush()
    db_session.add_all(
        [
            IngestionRunItem(
                ingestion_run_id=run.id,
                repository_full_name=repository.full_name,
                path=skill.path,
                status=IngestionItemStatus.INGESTED,
                reason=None,
                content_sha256=skill.content_sha256,
                duration_ms=2,
            ),
            IngestionRunItem(
                ingestion_run_id=run.id,
                repository_full_name=repository.full_name,
                path="skills/beta/SKILL.md",
                status=IngestionItemStatus.INVALID,
                reason=json.dumps(
                    {
                        "category": "validation",
                        "codes": ["field_required"],
                        "message": "Parser reported invalid skill content.",
                    }
                ),
                content_sha256="b" * 64,
                duration_ms=1,
            ),
        ]
    )
    db_session.flush()

    candidate_manifest = CandidateManifest(
        header=CandidateManifestHeader(
            generated_at=datetime(2030, 1, 1, tzinfo=UTC),
            git_commit="d" * 40,
            target_skills=2,
            target_reached=True,
            candidate_count=2,
            page_count=0,
            seed_repositories=(repository.full_name,),
            queries=("description filename:SKILL.md",),
        ),
        pages=(),
        candidates=(
            CandidateManifestCandidate(
                repository_id=repository.github_repository_id,
                repository_full_name=repository.full_name,
                repository_html_url=repository.html_url,
                path=skill.path,
                git_blob_sha=skill.git_blob_sha,
                html_url=skill.html_url,
                matched_queries=("description filename:SKILL.md",),
            ),
            CandidateManifestCandidate(
                repository_id=repository.github_repository_id,
                repository_full_name=repository.full_name,
                repository_html_url=repository.html_url,
                path="skills/beta/SKILL.md",
                git_blob_sha="2" * 40,
                html_url=(
                    "https://github.com/skillscope-tests/snapshot/blob/main/skills/beta/SKILL.md"
                ),
                matched_queries=("description filename:SKILL.md",),
            ),
        ),
    )

    snapshot = build_dataset_snapshot(
        db_session,
        candidate_manifest,
        ingestion_run_id=run.id,
        candidate_manifest_path=Path("data/manifests/candidates.jsonl"),
        generated_at=datetime(2030, 1, 2, tzinfo=UTC),
        git_commit="e" * 40,
    )

    assert snapshot.header.candidate_count == 2
    assert snapshot.header.stored_skill_count == 1
    assert snapshot.header.repository_count == 1
    assert snapshot.header.ingested_count == 1
    assert snapshot.header.invalid_count == 1
    assert snapshot.header.valid_skill_count == 1
    assert snapshot.items[0].stored is True
    assert snapshot.items[1].stored is False
    assert snapshot.items[1].failure is not None
    assert snapshot.items[1].failure["category"] == "validation"
