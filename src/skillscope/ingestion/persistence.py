"""Transactional repository and skill upserts for ingestion runs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from skillscope.db.enums import LicenseStatus
from skillscope.db.models import Repository, Skill, SkillFile
from skillscope.ingestion.discovery import SkillCandidate
from skillscope.ingestion.models import GitHubRepositoryPayload
from skillscope.parsing.models import ParsedSkill

_PERMISSIVE_SPDX_IDS = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "CC0-1.0",
        "ISC",
        "MIT",
        "MPL-2.0",
        "Unlicense",
    }
)
_UNKNOWN_SPDX_IDS = frozenset({"NOASSERTION", "OTHER"})
_WHITESPACE = re.compile(r"\s+")
MAX_SAFE_SNIPPET_CHARACTERS = 500


class PersistenceConflictError(RuntimeError):
    """Stored identities conflict with authoritative GitHub identifiers."""


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    """Stable repository fields needed after a short transaction closes."""

    database_id: UUID
    github_repository_id: int
    owner: str
    name: str
    full_name: str
    default_branch: str


@dataclass(frozen=True, slots=True)
class ExistingSkill:
    """The minimum stored state required for unchanged-SHA detection."""

    database_id: UUID
    git_blob_sha: str
    content_sha256: str


def classify_repository_license(payload: GitHubRepositoryPayload) -> LicenseStatus:
    """Map repository licence metadata conservatively and deterministically."""
    if payload.license is None:
        return LicenseStatus.MISSING

    spdx_id = payload.license.spdx_id
    if spdx_id is None or spdx_id.upper() in _UNKNOWN_SPDX_IDS:
        return LicenseStatus.UNKNOWN
    if spdx_id in _PERMISSIVE_SPDX_IDS:
        return LicenseStatus.PERMISSIVE
    return LicenseStatus.RESTRICTIVE


def upsert_repository(
    session: Session,
    payload: GitHubRepositoryPayload,
    *,
    etag: str | None,
    fetched_at: datetime | None = None,
) -> RepositoryContext:
    """Insert or refresh a repository using GitHub's stable numeric identity."""
    repository = session.scalar(
        select(Repository).where(Repository.github_repository_id == payload.id)
    )
    repository_with_name = session.scalar(
        select(Repository).where(Repository.full_name == payload.full_name)
    )
    if repository is None and repository_with_name is not None:
        raise PersistenceConflictError(
            "repository full name is already assigned to another GitHub repository ID"
        )
    if (
        repository is not None
        and repository_with_name is not None
        and repository.id != repository_with_name.id
    ):
        raise PersistenceConflictError(
            "repository ID and full name resolve to different stored repositories"
        )

    licence = payload.license
    values: dict[str, object] = {
        "owner": payload.owner.login,
        "name": payload.name,
        "full_name": payload.full_name,
        "html_url": payload.html_url,
        "default_branch": payload.default_branch,
        "description": payload.description,
        "stars_count": payload.stargazers_count,
        "forks_count": payload.forks_count,
        "open_issues_count": payload.open_issues_count,
        "is_fork": payload.fork,
        "is_archived": payload.archived,
        "license_spdx_id": licence.spdx_id if licence is not None else None,
        "license_name": licence.name if licence is not None else None,
        "license_status": classify_repository_license(payload),
        "pushed_at": payload.pushed_at,
        "fetched_at": fetched_at or datetime.now(UTC),
        "etag": etag,
    }
    if repository is None:
        repository = Repository(github_repository_id=payload.id, **values)
        session.add(repository)
    else:
        for field_name, value in values.items():
            setattr(repository, field_name, value)

    session.flush()
    return RepositoryContext(
        database_id=repository.id,
        github_repository_id=repository.github_repository_id,
        owner=repository.owner,
        name=repository.name,
        full_name=repository.full_name,
        default_branch=repository.default_branch,
    )


def find_existing_skill(
    session: Session,
    repository_id: UUID,
    path: str,
) -> ExistingSkill | None:
    """Return the stored SHA state for one repository path, if present."""
    skill = session.scalar(
        select(Skill).where(
            Skill.repository_id == repository_id,
            Skill.path == path,
        )
    )
    if skill is None:
        return None
    return ExistingSkill(
        database_id=skill.id,
        git_blob_sha=skill.git_blob_sha,
        content_sha256=skill.content_sha256,
    )


def mark_skill_seen(
    session: Session,
    skill_id: UUID,
    *,
    seen_at: datetime | None = None,
) -> None:
    """Advance freshness metadata without rewriting unchanged content."""
    skill = session.get(Skill, skill_id)
    if skill is None:
        raise PersistenceConflictError("stored skill disappeared during ingestion")
    skill.last_seen_at = seen_at or datetime.now(UTC)
    session.flush()


def upsert_skill(
    session: Session,
    repository: RepositoryContext,
    candidate: SkillCandidate,
    parsed: ParsedSkill,
    *,
    content_sha256: str,
    seen_at: datetime | None = None,
) -> Skill:
    """Insert or replace parsed skill fields and supporting-file metadata."""
    if parsed.frontmatter is None:
        raise ValueError("cannot persist a skill without valid required frontmatter")
    if candidate.repository_id != repository.github_repository_id:
        raise PersistenceConflictError("candidate repository ID changed during ingestion")
    if candidate.repository_full_name.casefold() != repository.full_name.casefold():
        raise PersistenceConflictError("candidate repository name changed during ingestion")
    if parsed.source_path != candidate.path:
        raise PersistenceConflictError("parser source path does not match the candidate path")
    skill = session.scalar(
        select(Skill).where(
            Skill.repository_id == repository.database_id,
            Skill.path == candidate.path,
        )
    )
    current_time = seen_at or datetime.now(UTC)
    values: dict[str, object] = {
        "html_url": candidate.html_url,
        "raw_url": None,
        "git_blob_sha": candidate.git_blob_sha,
        "content_sha256": content_sha256,
        "name": parsed.frontmatter.name,
        "description": parsed.frontmatter.description,
        "declared_license": parsed.frontmatter.license,
        "compatibility": parsed.frontmatter.compatibility,
        "allowed_tools": list(parsed.signals.declared_tools),
        "metadata_json": dict(parsed.frontmatter.metadata),
        "extension_fields_json": dict(parsed.extension_fields),
        "body_text": parsed.body_text,
        "search_text": _search_text(parsed),
        "safe_snippet": _safe_snippet(parsed.frontmatter.description),
        "embedding": None,
        "embedding_model_id": None,
        "embedding_model_revision": None,
        "embedding_config_sha256": None,
        "embedding_content_sha256": None,
        "embedding_text_sha256": None,
        "validation_status": parsed.validation_status,
        "validation_messages_json": [
            message.model_dump(mode="json") for message in parsed.validation_messages
        ],
        "has_scripts": parsed.signals.has_scripts,
        "has_references": parsed.signals.has_references,
        "has_assets": parsed.signals.has_assets,
        "script_count": parsed.signals.script_count,
        "reference_count": parsed.signals.reference_count,
        "asset_count": parsed.signals.asset_count,
        "heading_count": parsed.signals.heading_count,
        "code_block_count": parsed.signals.code_block_count,
        "external_link_count": parsed.signals.external_link_count,
        "word_count": parsed.signals.word_count,
        "byte_count": parsed.signals.byte_count,
        "last_seen_at": current_time,
        "indexed_at": None,
    }
    if skill is None:
        skill = Skill(
            repository_id=repository.database_id,
            path=candidate.path,
            **values,
        )
        session.add(skill)
        session.flush()
    else:
        for field_name, value in values.items():
            setattr(skill, field_name, value)
        session.execute(delete(SkillFile).where(SkillFile.skill_id == skill.id))

    supporting_file_models: list[SkillFile] = []
    for file in parsed.supporting_files:
        if file.git_blob_sha is None:
            raise PersistenceConflictError("supporting-file metadata is missing a Git blob SHA")
        supporting_file_models.append(
            SkillFile(
                skill_id=skill.id,
                relative_path=file.relative_path,
                file_type=file.file_type,
                size_bytes=file.size_bytes,
                git_blob_sha=file.git_blob_sha,
                extension=file.extension,
            )
        )
    session.add_all(supporting_file_models)
    session.flush()
    return skill


def _search_text(parsed: ParsedSkill) -> str:
    assert parsed.frontmatter is not None
    return "\n".join(
        (
            parsed.frontmatter.name,
            parsed.frontmatter.description,
            parsed.body_text,
        )
    )


def _safe_snippet(description: str) -> str:
    normalized = _WHITESPACE.sub(" ", description).strip()
    return normalized[:MAX_SAFE_SNIPPET_CHARACTERS]
