"""Tests for inert Markdown signals and bounded supporting-file metadata."""

from pathlib import Path

import pytest

from skillscope.db.enums import SupportingFileType, ValidationStatus
from skillscope.parsing.models import (
    DirectoryEntryKind,
    ParsedSkill,
    SkillDirectoryEntry,
    SkillSource,
)
from skillscope.parsing.parser import SkillParser
from skillscope.parsing.signals import MAX_DIRECTORY_ENTRIES

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "skills"


def _fixture_source(
    name: str,
    *,
    directory_entries: tuple[SkillDirectoryEntry, ...] = (),
) -> SkillSource:
    fixture = FIXTURE_ROOT / name / "SKILL.md"
    return SkillSource(
        path=f"{name}/SKILL.md",
        content=fixture.read_bytes(),
        directory_entries=directory_entries,
    )


def _parse_fixture(
    name: str,
    *,
    directory_entries: tuple[SkillDirectoryEntry, ...] = (),
) -> ParsedSkill:
    return SkillParser().parse(_fixture_source(name, directory_entries=directory_entries))


def _codes(result: ParsedSkill) -> list[str]:
    return [message.code for message in result.validation_messages]


def test_extracts_markdown_and_directory_signals_without_loading_files() -> None:
    entries = (
        SkillDirectoryEntry(relative_path="scripts", kind=DirectoryEntryKind.DIRECTORY),
        SkillDirectoryEntry(
            relative_path="scripts/run.py",
            kind=DirectoryEntryKind.FILE,
            size_bytes=120,
            git_blob_sha="a" * 40,
        ),
        SkillDirectoryEntry(relative_path="references", kind=DirectoryEntryKind.DIRECTORY),
        SkillDirectoryEntry(
            relative_path="references/guide.md",
            kind=DirectoryEntryKind.FILE,
            size_bytes=240,
            git_blob_sha="b" * 40,
        ),
        SkillDirectoryEntry(relative_path="assets", kind=DirectoryEntryKind.DIRECTORY),
        SkillDirectoryEntry(
            relative_path="assets/template.csv",
            kind=DirectoryEntryKind.FILE,
            size_bytes=360,
            git_blob_sha="c" * 40,
        ),
        SkillDirectoryEntry(
            relative_path="LICENSE.txt",
            kind=DirectoryEntryKind.FILE,
            size_bytes=480,
            git_blob_sha="d" * 40,
        ),
    )

    result = _parse_fixture("structural-signals", directory_entries=entries)

    assert result.validation_status is ValidationStatus.VALID
    assert result.signals.headings == ("Overview", "Usage")
    assert result.signals.heading_count == 2
    assert result.signals.code_block_count == 2
    assert result.signals.link_count == 4
    assert result.signals.external_link_count == 2
    assert result.signals.referenced_paths == (
        "references/guide.md",
        "assets/template.csv",
    )
    assert result.signals.declared_tools == ("Read", "Bash(git:*)", "Grep")
    assert result.signals.word_count > 0
    assert result.signals.byte_count == len(
        (FIXTURE_ROOT / "structural-signals" / "SKILL.md").read_bytes()
    )
    assert result.signals.has_scripts is True
    assert result.signals.has_references is True
    assert result.signals.has_assets is True
    assert result.signals.script_count == 1
    assert result.signals.reference_count == 1
    assert result.signals.asset_count == 1
    assert [file.relative_path for file in result.supporting_files] == [
        "LICENSE.txt",
        "assets/template.csv",
        "references/guide.md",
        "scripts/run.py",
    ]
    assert [file.file_type for file in result.supporting_files] == [
        SupportingFileType.OTHER,
        SupportingFileType.ASSET,
        SupportingFileType.REFERENCE,
        SupportingFileType.SCRIPT,
    ]


def test_code_fences_do_not_create_heading_or_link_signals() -> None:
    result = _parse_fixture("structural-signals")

    assert "This is code, not a heading." not in result.signals.headings
    assert result.signals.external_link_count == 2


def test_referenced_path_traversal_is_invalid_and_never_retained() -> None:
    result = _parse_fixture("path-traversal-reference")

    assert result.validation_status is ValidationStatus.INVALID
    assert result.signals.referenced_paths == ()
    assert _codes(result).count("unsafe_referenced_path") == 2


def test_malformed_link_is_a_warning_instead_of_an_exception() -> None:
    result = _parse_fixture("malformed-link")

    assert result.validation_status is ValidationStatus.WARNING
    assert "malformed_link_destination" in _codes(result)
    assert result.signals.external_link_count == 0


def test_unsafe_and_duplicate_supporting_paths_are_reported() -> None:
    entries = (
        SkillDirectoryEntry(
            relative_path="scripts/run.py",
            kind=DirectoryEntryKind.FILE,
            size_bytes=10,
        ),
        SkillDirectoryEntry(
            relative_path="scripts/run.py",
            kind=DirectoryEntryKind.FILE,
            size_bytes=10,
        ),
        SkillDirectoryEntry(
            relative_path="references/%2e%2e/secret.md",
            kind=DirectoryEntryKind.FILE,
            size_bytes=10,
        ),
    )

    result = _parse_fixture("minimal-valid", directory_entries=entries)

    assert result.validation_status is ValidationStatus.INVALID
    assert set(_codes(result)) == {"duplicate_supporting_path", "unsafe_supporting_path"}
    assert [file.relative_path for file in result.supporting_files] == ["scripts/run.py"]

    encoded_source = SkillParser().parse(
        SkillSource(
            path="skills/%2e%2e/minimal-valid/SKILL.md",
            content=(FIXTURE_ROOT / "minimal-valid" / "SKILL.md").read_bytes(),
        )
    )
    assert "invalid_source_path" in _codes(encoded_source)


def test_directory_entry_limit_is_enforced_deterministically() -> None:
    entries = tuple(
        SkillDirectoryEntry(
            relative_path=f"other/file-{index:04d}.txt",
            kind=DirectoryEntryKind.FILE,
            size_bytes=index,
        )
        for index in reversed(range(MAX_DIRECTORY_ENTRIES + 1))
    )

    result = _parse_fixture("minimal-valid", directory_entries=entries)

    assert result.validation_status is ValidationStatus.INVALID
    assert "too_many_directory_entries" in _codes(result)
    assert result.supporting_files == ()
    assert result.signals.script_count == 0


def test_empty_body_invalid_utf8_and_strict_yaml_types_are_reported() -> None:
    empty = _parse_fixture("empty-body")
    invalid_name = _parse_fixture("invalid-name")
    invalid_metadata = _parse_fixture("invalid-metadata")
    invalid_extension = _parse_fixture("invalid-extension-type")
    invalid_utf8 = SkillParser().parse(
        SkillSource(
            path="invalid-utf8/SKILL.md",
            content=b"---\nname: invalid-utf8\ndescription: Broken.\n---\n\xff",
        )
    )

    assert empty.validation_status is ValidationStatus.WARNING
    assert "empty_body" in _codes(empty)
    assert invalid_name.validation_status is ValidationStatus.INVALID
    assert "field_invalid" in _codes(invalid_name)
    assert invalid_metadata.validation_status is ValidationStatus.INVALID
    assert "field_invalid" in _codes(invalid_metadata)
    assert invalid_extension.validation_status is ValidationStatus.INVALID
    assert "extension_value_not_json" in _codes(invalid_extension)
    assert invalid_utf8.validation_status is ValidationStatus.INVALID
    assert "invalid_utf8" in _codes(invalid_utf8)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("name", "a" * 65),
        ("description", "a" * 1_025),
        ("compatibility", "a" * 501),
    ],
)
def test_overlong_standard_fields_are_invalid(field: str, value: str) -> None:
    values = {
        "name": "overlong-fields",
        "description": "Checks field limits.",
        field: value,
    }
    frontmatter = "\n".join(f"{key}: {item}" for key, item in values.items())
    result = SkillParser().parse(
        SkillSource(
            path="overlong-fields/SKILL.md",
            content=f"---\n{frontmatter}\n---\nBody.\n".encode(),
        )
    )

    assert result.validation_status is ValidationStatus.INVALID
    assert any(
        message.code == "field_invalid" and message.field == field
        for message in result.validation_messages
    )
