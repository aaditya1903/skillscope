"""Deterministic structural analysis of inert Markdown and directory metadata."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import SplitResult, unquote, urlsplit

from skillscope.db.enums import SupportingFileType
from skillscope.parsing.models import (
    DirectoryEntryKind,
    SkillDirectoryEntry,
    StructuralSignals,
    SupportingFileMetadata,
    ValidationMessage,
    ValidationSeverity,
)

MAX_DIRECTORY_ENTRIES = 1_000
MAX_RELATIVE_PATH_LENGTH = 1_024

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_HEADING_RE = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)\s*$")
_INLINE_LINK_RE = re.compile(r"!?\[[^\]\n]*\]\(([^)\n]+)\)")
_REFERENCE_LINK_RE = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*(\S+)", re.MULTILINE)
_AUTOLINK_RE = re.compile(r"<((?:https?://)[^>\s]+)>")
_WORD_RE = re.compile(r"\b[\w][\w'+-]*\b", re.UNICODE)


@dataclass(frozen=True, slots=True)
class SignalExtraction:
    """Signals, safe supporting metadata, and any security findings."""

    signals: StructuralSignals
    supporting_files: tuple[SupportingFileMetadata, ...]
    validation_messages: tuple[ValidationMessage, ...]


def extract_structural_signals(
    *,
    body_text: str,
    source_byte_count: int,
    allowed_tools: str | None,
    directory_entries: tuple[SkillDirectoryEntry, ...],
) -> SignalExtraction:
    """Extract bounded signals in linear time with respect to supplied input."""

    visible_text, headings, code_block_count = _scan_markdown(body_text)
    destinations = _link_destinations(visible_text)
    referenced_paths, link_messages = _referenced_paths(destinations)
    external_link_count = sum(_is_external_http_url(destination) for destination in destinations)
    directory = _directory_signals(directory_entries)

    signals = StructuralSignals(
        headings=headings,
        referenced_paths=referenced_paths,
        declared_tools=_stable_unique((allowed_tools or "").split()),
        heading_count=len(headings),
        code_block_count=code_block_count,
        link_count=len(destinations),
        external_link_count=external_link_count,
        word_count=len(_WORD_RE.findall(visible_text)),
        byte_count=source_byte_count,
        has_scripts=directory.has_scripts,
        has_references=directory.has_references,
        has_assets=directory.has_assets,
        script_count=directory.script_count,
        reference_count=directory.reference_count,
        asset_count=directory.asset_count,
    )

    return SignalExtraction(
        signals=signals,
        supporting_files=directory.supporting_files,
        validation_messages=(*link_messages, *directory.validation_messages),
    )


@dataclass(frozen=True, slots=True)
class _DirectorySignals:
    has_scripts: bool
    has_references: bool
    has_assets: bool
    script_count: int
    reference_count: int
    asset_count: int
    supporting_files: tuple[SupportingFileMetadata, ...]
    validation_messages: tuple[ValidationMessage, ...]


def _scan_markdown(body_text: str) -> tuple[str, tuple[str, ...], int]:
    visible_lines: list[str] = []
    headings: list[str] = []
    fence_character: str | None = None
    fence_length = 0
    code_block_count = 0

    for line in body_text.splitlines():
        fence_match = _FENCE_OPEN_RE.match(line)
        if fence_character is None:
            if fence_match is not None:
                fence = fence_match.group(1)
                fence_character = fence[0]
                fence_length = len(fence)
                code_block_count += 1
                continue

            visible_lines.append(line)
            heading_match = _HEADING_RE.match(line)
            if heading_match is not None:
                heading = re.sub(r"[ \t]+#+[ \t]*$", "", heading_match.group(1)).strip()
                if heading:
                    headings.append(heading)
            continue

        if _is_closing_fence(line, fence_character, fence_length):
            fence_character = None
            fence_length = 0

    return "\n".join(visible_lines), tuple(headings), code_block_count


def _is_closing_fence(line: str, character: str, minimum_length: int) -> bool:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3 or not stripped.startswith(character * minimum_length):
        return False

    run_length = len(stripped) - len(stripped.lstrip(character))
    return run_length >= minimum_length and not stripped[run_length:].strip()


def _link_destinations(markdown_text: str) -> tuple[str, ...]:
    destinations: list[str] = []
    for match in _INLINE_LINK_RE.finditer(markdown_text):
        destination = _normalise_link_destination(match.group(1))
        if destination:
            destinations.append(destination)

    destinations.extend(match.group(1) for match in _REFERENCE_LINK_RE.finditer(markdown_text))
    destinations.extend(match.group(1) for match in _AUTOLINK_RE.finditer(markdown_text))
    return tuple(destinations)


def _normalise_link_destination(raw_destination: str) -> str:
    destination = raw_destination.strip()
    if destination.startswith("<") and ">" in destination:
        return destination[1 : destination.index(">")]

    # A title follows the URL after whitespace in ordinary inline Markdown links.
    return destination.split(maxsplit=1)[0] if destination else ""


def _referenced_paths(
    destinations: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[ValidationMessage, ...]]:
    referenced_paths: list[str] = []
    messages: list[ValidationMessage] = []

    for destination in destinations:
        parsed = _safe_urlsplit(destination)
        if parsed is None:
            messages.append(
                ValidationMessage(
                    code="malformed_link_destination",
                    severity=ValidationSeverity.WARNING,
                    message="Malformed Markdown link destination was ignored.",
                    field="body",
                )
            )
            continue
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue

        decoded_path = unquote(parsed.path)
        if decoded_path.startswith("/") or not _is_safe_relative_path(decoded_path):
            messages.append(
                ValidationMessage(
                    code="unsafe_referenced_path",
                    severity=ValidationSeverity.INVALID,
                    message="Referenced paths must stay within the skill directory.",
                    field="body",
                )
            )
            continue

        referenced_paths.append(decoded_path)

    return _stable_unique(referenced_paths), tuple(messages)


def _directory_signals(entries: tuple[SkillDirectoryEntry, ...]) -> _DirectorySignals:
    messages: list[ValidationMessage] = []
    if len(entries) > MAX_DIRECTORY_ENTRIES:
        message = ValidationMessage(
            code="too_many_directory_entries",
            severity=ValidationSeverity.INVALID,
            message=f"Skill directory exceeds the {MAX_DIRECTORY_ENTRIES}-entry limit.",
            field="directory_entries",
        )
        return _DirectorySignals(
            has_scripts=False,
            has_references=False,
            has_assets=False,
            script_count=0,
            reference_count=0,
            asset_count=0,
            supporting_files=(),
            validation_messages=(message,),
        )

    sorted_entries = tuple(sorted(entries, key=lambda item: item.relative_path))

    has_scripts = False
    has_references = False
    has_assets = False
    supporting_files: list[SupportingFileMetadata] = []
    seen_paths: set[str] = set()

    for entry in sorted_entries:
        path = entry.relative_path
        if not _is_safe_relative_path(path):
            messages.append(
                ValidationMessage(
                    code="unsafe_supporting_path",
                    severity=ValidationSeverity.INVALID,
                    message="Supporting paths must stay within the skill directory.",
                    field="directory_entries",
                )
            )
            continue

        if path in seen_paths:
            messages.append(
                ValidationMessage(
                    code="duplicate_supporting_path",
                    severity=ValidationSeverity.WARNING,
                    message="Duplicate supporting-file metadata was ignored.",
                    field="directory_entries",
                )
            )
            continue
        seen_paths.add(path)

        file_type = _supporting_file_type(path)
        has_scripts = has_scripts or _belongs_to(path, "scripts")
        has_references = has_references or _belongs_to(path, "references")
        has_assets = has_assets or _belongs_to(path, "assets")

        if entry.kind is DirectoryEntryKind.DIRECTORY or path == "SKILL.md":
            continue

        suffix = PurePosixPath(path).suffix.lower().removeprefix(".") or None
        supporting_files.append(
            SupportingFileMetadata(
                relative_path=path,
                file_type=file_type,
                size_bytes=entry.size_bytes,
                git_blob_sha=entry.git_blob_sha,
                extension=suffix,
            )
        )

    script_count = sum(file.file_type is SupportingFileType.SCRIPT for file in supporting_files)
    reference_count = sum(
        file.file_type is SupportingFileType.REFERENCE for file in supporting_files
    )
    asset_count = sum(file.file_type is SupportingFileType.ASSET for file in supporting_files)

    return _DirectorySignals(
        has_scripts=has_scripts,
        has_references=has_references,
        has_assets=has_assets,
        script_count=script_count,
        reference_count=reference_count,
        asset_count=asset_count,
        supporting_files=tuple(supporting_files),
        validation_messages=tuple(messages),
    )


def _supporting_file_type(path: str) -> SupportingFileType:
    if _belongs_to(path, "scripts"):
        return SupportingFileType.SCRIPT
    if _belongs_to(path, "references"):
        return SupportingFileType.REFERENCE
    if _belongs_to(path, "assets"):
        return SupportingFileType.ASSET
    return SupportingFileType.OTHER


def _belongs_to(path: str, directory: str) -> bool:
    return path == directory or path.startswith(f"{directory}/")


def _is_safe_relative_path(path: str) -> bool:
    decoded_path = unquote(path)
    if (
        not decoded_path
        or len(decoded_path) > MAX_RELATIVE_PATH_LENGTH
        or decoded_path.startswith("/")
        or "\\" in decoded_path
        or any(ord(character) < 32 for character in decoded_path)
    ):
        return False

    return all(part not in {"", ".", ".."} for part in decoded_path.split("/"))


def _is_external_http_url(destination: str) -> bool:
    parsed = _safe_urlsplit(destination)
    return parsed is not None and parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)


def _safe_urlsplit(destination: str) -> SplitResult | None:
    try:
        return urlsplit(destination)
    except ValueError:
        return None


def _stable_unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
