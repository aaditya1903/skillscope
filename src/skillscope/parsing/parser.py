"""Safe YAML loading and validation for untrusted Agent Skills files."""

from __future__ import annotations

from collections.abc import Hashable, Mapping
from pathlib import PurePosixPath
from urllib.parse import unquote

import yaml
from pydantic import JsonValue, TypeAdapter, ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, Node
from yaml.tokens import AliasToken, AnchorToken

from skillscope.db.enums import ValidationStatus
from skillscope.parsing.frontmatter import FrontmatterError, extract_frontmatter
from skillscope.parsing.models import (
    ParsedSkill,
    SkillFrontmatter,
    SkillSource,
    ValidationMessage,
    ValidationSeverity,
)
from skillscope.parsing.signals import MAX_RELATIVE_PATH_LENGTH, extract_structural_signals

STANDARD_FIELDS = frozenset(
    {
        "name",
        "description",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
    }
)
_JSON_VALUE_ADAPTER: TypeAdapter[JsonValue] = TypeAdapter(JsonValue)


class _UniqueKeySafeLoader(yaml.SafeLoader):
    """SafeLoader variant that rejects ambiguous duplicate mapping keys."""

    def construct_mapping(
        self,
        node: Node,
        deep: bool = False,
    ) -> dict[object, object]:
        if not isinstance(node, MappingNode):
            raise ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "expected a mapping node",
                node.start_mark,
            )

        self.flatten_mapping(node)
        mapping: dict[object, object] = {}

        for key_node, value_node in node.value:
            key: object = self.construct_object(key_node, deep=deep)
            if not isinstance(key, Hashable):
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                )
            if key in mapping:
                raise ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)

        return mapping


class SkillParser:
    """Parse one untrusted ``SKILL.md`` into data and explicit findings."""

    def parse(self, source: SkillSource) -> ParsedSkill:
        messages = _validate_source_path(source.path)

        try:
            document = extract_frontmatter(source.content)
        except FrontmatterError as exc:
            messages.append(_invalid(exc.code, str(exc)))
            return _result(source, None, {}, "", messages)

        try:
            raw_mapping = _load_yaml_mapping(document.frontmatter_text)
        except yaml.YAMLError as exc:
            messages.append(
                _invalid(
                    "invalid_yaml",
                    f"YAML frontmatter could not be parsed safely: {_yaml_problem(exc)}",
                )
            )
            return _result(source, None, {}, document.body_text, messages)

        if not isinstance(raw_mapping, Mapping):
            messages.append(
                _invalid(
                    "frontmatter_not_mapping",
                    "YAML frontmatter must be a mapping of field names to values.",
                )
            )
            return _result(source, None, {}, document.body_text, messages)

        standard_values: dict[str, object] = {}
        extension_values: dict[str, JsonValue] = {}

        for raw_key, raw_value in raw_mapping.items():
            if not isinstance(raw_key, str):
                messages.append(
                    _invalid(
                        "non_string_field_name",
                        "Every YAML frontmatter field name must be a string.",
                    )
                )
                continue

            if raw_key in STANDARD_FIELDS:
                standard_values[raw_key] = raw_value
                continue

            try:
                extension_values[raw_key] = _JSON_VALUE_ADAPTER.validate_python(
                    raw_value,
                    strict=True,
                )
            except ValidationError:
                messages.append(
                    _invalid(
                        "extension_value_not_json",
                        "Extension field values must be JSON-compatible.",
                        field=raw_key,
                    )
                )
                continue

            messages.append(
                _warning(
                    "extension_field",
                    "Unknown frontmatter field was preserved as an extension.",
                    field=raw_key,
                )
            )

        frontmatter: SkillFrontmatter | None
        try:
            frontmatter = SkillFrontmatter.model_validate(standard_values)
        except ValidationError as exc:
            frontmatter = None
            messages.extend(_pydantic_messages(exc))

        if frontmatter is not None and _path_is_valid(source.path):
            parent_name = PurePosixPath(unquote(source.path)).parent.name
            if not parent_name:
                messages.append(
                    _warning(
                        "root_directory_name_unverified",
                        "The name-to-parent-directory rule cannot be verified for a "
                        "repository-root SKILL.md.",
                        field="name",
                    )
                )
            elif frontmatter.name != parent_name:
                messages.append(
                    _invalid(
                        "name_directory_mismatch",
                        "The name field must match the parent directory name.",
                        field="name",
                    )
                )

        if not document.body_text.strip():
            messages.append(
                _warning(
                    "empty_body",
                    "SKILL.md has no Markdown instructions after its frontmatter.",
                )
            )

        return _result(
            source,
            frontmatter,
            extension_values,
            document.body_text,
            messages,
        )


def _load_yaml_mapping(frontmatter_text: str) -> object:
    tokens = yaml.scan(frontmatter_text, Loader=_UniqueKeySafeLoader)
    if any(isinstance(token, (AliasToken, AnchorToken)) for token in tokens):
        raise ConstructorError(
            None,
            None,
            "YAML anchors and aliases are not supported",
            None,
        )

    loaded: object = yaml.load(frontmatter_text, Loader=_UniqueKeySafeLoader)
    return loaded


def _validate_source_path(path: str) -> list[ValidationMessage]:
    if not _path_is_valid(path):
        return [
            _invalid(
                "invalid_source_path",
                "Source path must be a safe relative path ending in SKILL.md.",
                field="path",
            )
        ]
    return []


def _path_is_valid(path: str) -> bool:
    decoded_path = unquote(path)
    if (
        not decoded_path
        or len(decoded_path) > MAX_RELATIVE_PATH_LENGTH
        or decoded_path.startswith("/")
        or "\\" in decoded_path
        or any(ord(character) < 32 for character in decoded_path)
    ):
        return False

    parts = decoded_path.split("/")
    return parts[-1] == "SKILL.md" and all(part not in {"", ".", ".."} for part in parts)


def _pydantic_messages(error: ValidationError) -> list[ValidationMessage]:
    messages: list[ValidationMessage] = []
    for detail in error.errors(include_url=False):
        location = detail.get("loc", ())
        field = str(location[0]) if location else None
        code = "field_required" if detail.get("type") == "missing" else "field_invalid"
        messages.append(
            _invalid(
                code,
                detail.get("msg", "Frontmatter field is invalid."),
                field=field,
            )
        )
    return messages


def _result(
    source: SkillSource,
    frontmatter: SkillFrontmatter | None,
    extension_fields: dict[str, JsonValue],
    body_text: str,
    messages: list[ValidationMessage],
) -> ParsedSkill:
    signal_extraction = extract_structural_signals(
        body_text=body_text,
        source_byte_count=len(source.content),
        allowed_tools=frontmatter.allowed_tools if frontmatter is not None else None,
        directory_entries=source.directory_entries,
    )
    messages.extend(signal_extraction.validation_messages)

    if any(message.severity is ValidationSeverity.INVALID for message in messages):
        status = ValidationStatus.INVALID
    elif messages:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.VALID

    return ParsedSkill(
        source_path=source.path,
        frontmatter=frontmatter,
        extension_fields=extension_fields,
        body_text=body_text,
        signals=signal_extraction.signals,
        supporting_files=signal_extraction.supporting_files,
        validation_status=status,
        validation_messages=tuple(messages),
    )


def _warning(code: str, message: str, *, field: str | None = None) -> ValidationMessage:
    return ValidationMessage(
        code=code,
        severity=ValidationSeverity.WARNING,
        message=message,
        field=field,
    )


def _invalid(code: str, message: str, *, field: str | None = None) -> ValidationMessage:
    return ValidationMessage(
        code=code,
        severity=ValidationSeverity.INVALID,
        message=message,
        field=field,
    )


def _yaml_problem(error: yaml.YAMLError) -> str:
    problem = getattr(error, "problem", None)
    return problem if isinstance(problem, str) else "invalid YAML"
