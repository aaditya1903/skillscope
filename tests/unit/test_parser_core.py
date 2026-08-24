"""Tests for bounded, inert, standards-aware SKILL.md parsing."""

from pathlib import Path

from skillscope.db.enums import ValidationStatus
from skillscope.parsing.frontmatter import MAX_FRONTMATTER_BYTES, MAX_SKILL_BYTES
from skillscope.parsing.models import ParsedSkill, SkillSource
from skillscope.parsing.parser import SkillParser

FIXTURE_ROOT = Path(__file__).parents[1] / "fixtures" / "skills"


def _parse(path: str, text: str) -> ParsedSkill:
    return SkillParser().parse(SkillSource(path=path, content=text.encode()))


def _parse_fixture(name: str) -> ParsedSkill:
    fixture = FIXTURE_ROOT / name / "SKILL.md"
    return SkillParser().parse(
        SkillSource(
            path=f"{name}/SKILL.md",
            content=fixture.read_bytes(),
        )
    )


def _codes(result: ParsedSkill) -> set[str]:
    return {message.code for message in result.validation_messages}


def test_minimal_valid_skill() -> None:
    result = _parse_fixture("minimal-valid")

    assert result.validation_status is ValidationStatus.VALID
    assert result.frontmatter is not None
    assert result.frontmatter.name == "minimal-valid"
    assert result.body_text.startswith("# Minimal valid skill")


def test_extensions_are_preserved_as_warnings() -> None:
    result = _parse_fixture("fully-populated")

    assert result.validation_status is ValidationStatus.WARNING
    assert result.extension_fields == {"x-vendor": {"enabled": True}}
    assert _codes(result) == {"extension_field"}


def test_missing_required_fields_are_reported_together() -> None:
    result = _parse("missing-fields/SKILL.md", "---\nlicense: MIT\n---\nBody\n")

    required_fields = {
        message.field for message in result.validation_messages if message.code == "field_required"
    }
    assert result.validation_status is ValidationStatus.INVALID
    assert required_fields == {"name", "description"}


def test_invalid_name_and_directory_mismatch() -> None:
    invalid_name = _parse(
        "bad-name/SKILL.md",
        "---\nname: bad--name\ndescription: Invalid name example.\n---\nBody\n",
    )
    mismatch = _parse(
        "actual-directory/SKILL.md",
        "---\nname: other-directory\ndescription: Directory mismatch example.\n---\nBody\n",
    )

    assert "field_invalid" in _codes(invalid_name)
    assert "name_directory_mismatch" in _codes(mismatch)


def test_repository_root_skill_is_safe_with_an_explicit_verification_warning() -> None:
    result = _parse(
        "SKILL.md",
        "---\n"
        "name: portable-root-skill\n"
        "description: A repository-root skill with no encoded parent directory.\n"
        "---\n"
        "Body\n",
    )

    assert result.validation_status is ValidationStatus.WARNING
    assert _codes(result) == {"root_directory_name_unverified"}


def test_crlf_and_non_ascii_body_are_accepted() -> None:
    crlf_result = _parse(
        "multilingual/SKILL.md",
        "---\r\n"
        "name: multilingual\r\n"
        "description: Handles multilingual text when needed.\r\n"
        "---\r\n"
        "Résumé 日本語\r\n",
    )
    fixture_result = _parse_fixture("non-ascii")

    assert crlf_result.validation_status is ValidationStatus.VALID
    assert crlf_result.body_text == "Résumé 日本語\n"
    assert fixture_result.validation_status is ValidationStatus.VALID
    assert "日本語" in fixture_result.body_text


def test_prompt_injection_body_remains_inert_text(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    fixture = (FIXTURE_ROOT / "prompt-injection" / "SKILL.md").read_text()
    source_text = fixture.replace("{{MARKER_PATH}}", str(marker))
    result = SkillParser().parse(
        SkillSource(
            path="prompt-injection/SKILL.md",
            content=source_text.encode(),
        )
    )

    assert str(marker) in result.body_text
    assert not marker.exists()


def test_unsafe_yaml_tag_is_rejected_without_execution(tmp_path: Path) -> None:
    marker = tmp_path / "must-not-exist"
    result = _parse(
        "unsafe-yaml/SKILL.md",
        "---\n"
        "name: unsafe-yaml\n"
        "description: Rejects unsafe YAML tags.\n"
        f"payload: !!python/object/apply:os.system ['touch {marker}']\n"
        "---\nBody\n",
    )

    assert result.validation_status is ValidationStatus.INVALID
    assert "invalid_yaml" in _codes(result)
    assert not marker.exists()


def test_aliases_and_duplicate_keys_are_rejected() -> None:
    alias = _parse(
        "aliases/SKILL.md",
        "---\nname: &name aliases\ndescription: *name\n---\nBody\n",
    )
    duplicate = _parse(
        "duplicates/SKILL.md",
        "---\nname: duplicates\nname: replaced\ndescription: Duplicate key.\n---\nBody\n",
    )

    assert "invalid_yaml" in _codes(alias)
    assert "invalid_yaml" in _codes(duplicate)


def test_file_and_frontmatter_limits_are_enforced() -> None:
    oversized_file = SkillSource(
        path="oversized/SKILL.md",
        content=b"x" * (MAX_SKILL_BYTES + 1),
    )
    oversized_frontmatter = (
        f"---\nname: oversized\ndescription: {'x' * MAX_FRONTMATTER_BYTES}\n---\nBody\n"
    )

    file_result = SkillParser().parse(oversized_file)
    frontmatter_result = _parse("oversized/SKILL.md", oversized_frontmatter)

    assert "file_too_large" in _codes(file_result)
    assert "frontmatter_too_large" in _codes(frontmatter_result)


def test_malformed_documents_and_paths_return_findings() -> None:
    no_opening = _parse("missing-opening/SKILL.md", "name: missing-opening\n")
    no_closing = _parse(
        "missing-closing/SKILL.md",
        "---\nname: missing-closing\ndescription: Missing delimiter.\n",
    )
    yaml_list = _parse("yaml-list/SKILL.md", "---\n- one\n- two\n---\nBody\n")
    traversal = _parse(
        "../traversal/SKILL.md",
        "---\nname: traversal\ndescription: Invalid path.\n---\nBody\n",
    )

    assert "missing_opening_delimiter" in _codes(no_opening)
    assert "missing_closing_delimiter" in _codes(no_closing)
    assert "frontmatter_not_mapping" in _codes(yaml_list)
    assert "invalid_source_path" in _codes(traversal)
