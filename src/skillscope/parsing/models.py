"""Typed parser inputs, outputs, and Agent Skills frontmatter fields."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    StrictStr,
    StringConstraints,
)

from skillscope.db.enums import SupportingFileType, ValidationStatus

SkillName = Annotated[
    StrictStr,
    StringConstraints(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]
Description = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=1024),
]
OptionalNonEmptyString = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1),
]
Compatibility = Annotated[
    StrictStr,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500),
]


class ValidationSeverity(StrEnum):
    """Severity attached to one parser validation message."""

    WARNING = "warning"
    INVALID = "invalid"


class DirectoryEntryKind(StrEnum):
    """Kind of one bounded entry below a skill directory."""

    FILE = "file"
    DIRECTORY = "directory"


class ValidationMessage(BaseModel):
    """One stable, machine-readable parser finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: ValidationSeverity
    message: str
    field: str | None = None


class SkillDirectoryEntry(BaseModel):
    """Untrusted metadata for one file or directory near ``SKILL.md``."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    relative_path: str
    kind: DirectoryEntryKind
    size_bytes: int = Field(default=0, ge=0)
    git_blob_sha: str | None = None


class SkillSource(BaseModel):
    """Untrusted bytes and their repository-relative path."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str
    content: bytes
    directory_entries: tuple[SkillDirectoryEntry, ...] = ()


class SkillFrontmatter(BaseModel):
    """Standard fields defined by the Agent Skills specification."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        strict=True,
    )

    name: SkillName
    description: Description
    license: OptionalNonEmptyString | None = None
    compatibility: Compatibility | None = None
    metadata: dict[StrictStr, StrictStr] = Field(default_factory=dict)
    allowed_tools: OptionalNonEmptyString | None = Field(
        default=None,
        alias="allowed-tools",
    )


class SupportingFileMetadata(BaseModel):
    """Safe metadata retained for a supporting file, never its contents."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str
    file_type: SupportingFileType
    size_bytes: int
    git_blob_sha: str | None = None
    extension: str | None = None


class StructuralSignals(BaseModel):
    """Interpretable signals extracted without rendering or executing content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    headings: tuple[str, ...] = ()
    referenced_paths: tuple[str, ...] = ()
    declared_tools: tuple[str, ...] = ()
    heading_count: int = 0
    code_block_count: int = 0
    link_count: int = 0
    external_link_count: int = 0
    word_count: int = 0
    byte_count: int = 0
    has_scripts: bool = False
    has_references: bool = False
    has_assets: bool = False
    script_count: int = 0
    reference_count: int = 0
    asset_count: int = 0


class ParsedSkill(BaseModel):
    """Safe parser result, including invalid and warning outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    frontmatter: SkillFrontmatter | None
    extension_fields: dict[str, JsonValue] = Field(default_factory=dict)
    body_text: str
    signals: StructuralSignals
    supporting_files: tuple[SupportingFileMetadata, ...] = ()
    validation_status: ValidationStatus
    validation_messages: tuple[ValidationMessage, ...] = ()
