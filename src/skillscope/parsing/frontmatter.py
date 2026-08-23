"""Bounded extraction of YAML frontmatter from untrusted bytes."""

from __future__ import annotations

from dataclasses import dataclass

MAX_SKILL_BYTES = 256 * 1024
MAX_FRONTMATTER_BYTES = 16 * 1024


class FrontmatterError(ValueError):
    """A safe, expected failure while extracting an untrusted document."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    """Normalised frontmatter and Markdown body."""

    frontmatter_text: str
    body_text: str


def extract_frontmatter(content: bytes) -> ExtractedDocument:
    """Decode, normalise, and split one bounded ``SKILL.md`` document.

    The operation is linear in the input size and allocates at most a constant
    number of copies of an input already capped at ``MAX_SKILL_BYTES``.
    """

    if len(content) > MAX_SKILL_BYTES:
        raise FrontmatterError(
            "file_too_large",
            f"SKILL.md exceeds the {MAX_SKILL_BYTES}-byte limit.",
        )

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise FrontmatterError(
            "invalid_utf8",
            "SKILL.md must contain valid UTF-8 text.",
        ) from exc

    normalised = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalised.split("\n")

    if not lines or lines[0] != "---":
        raise FrontmatterError(
            "missing_opening_delimiter",
            "SKILL.md must begin with a YAML frontmatter delimiter.",
        )

    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line == "---"),
        None,
    )
    if closing_index is None:
        raise FrontmatterError(
            "missing_closing_delimiter",
            "YAML frontmatter is missing its closing delimiter.",
        )

    frontmatter_text = "\n".join(lines[1:closing_index])
    if len(frontmatter_text.encode("utf-8")) > MAX_FRONTMATTER_BYTES:
        raise FrontmatterError(
            "frontmatter_too_large",
            f"YAML frontmatter exceeds the {MAX_FRONTMATTER_BYTES}-byte limit.",
        )

    return ExtractedDocument(
        frontmatter_text=frontmatter_text,
        body_text="\n".join(lines[closing_index + 1 :]),
    )
