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

from skillscope.db.enums import ValidationStatus

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


class ValidationMessage(BaseModel):
    """One stable, machine-readable parser finding."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    severity: ValidationSeverity
    message: str
    field: str | None = None


class SkillSource(BaseModel):
    """Untrusted bytes and their repository-relative path."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    path: str
    content: bytes


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


class ParsedSkill(BaseModel):
    """Safe parser result, including invalid and warning outcomes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_path: str
    frontmatter: SkillFrontmatter | None
    extension_fields: dict[str, JsonValue] = Field(default_factory=dict)
    body_text: str
    validation_status: ValidationStatus
    validation_messages: tuple[ValidationMessage, ...] = ()
