"""Documented Unicode and Markdown processing for lexical retrieval."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Final, Literal

TOKENIZER_VERSION: Final[Literal["unicode-nfkc-markdown-v1"]] = "unicode-nfkc-markdown-v1"

# A token begins with one or more Unicode letters or digits. Internal dots,
# slashes, colons, underscores, and hyphens retain common technical names;
# terminal ``+``, ``++``, and ``#`` retain language names such as C++ and C#.
TOKEN_PATTERN_TEXT: Final = r"[^\W_]+(?:(?:[./:_-][^\W_]+)|(?:\+\+|\+|#))*"
TOKEN_PATTERN = re.compile(TOKEN_PATTERN_TEXT, flags=re.UNICODE)

_HTML_COMMENT = re.compile(r"<!--.*?-->", flags=re.DOTALL)
_HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
_AUTOLINK = re.compile(r"<(?:https?://|mailto:)[^>]+>", flags=re.IGNORECASE)
_IMAGE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_REFERENCE_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_INLINE_CODE = re.compile(r"`+([^`\n]+?)`+")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})(.*)$")
_ATX_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$")
_SETEXT_UNDERLINE = re.compile(r"^[ \t]{0,3}(?:=+|-+)[ \t]*$")
_BLOCK_PREFIX = re.compile(
    r"^[ \t]{0,3}(?:>[ \t]?|[-+*][ \t]+|\d+[.)][ \t]+)",
    flags=re.MULTILINE,
)
_WHITESPACE = re.compile(r"\s+")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.;:!?])")


def normalize_lexical_text(text: str) -> str:
    """Return inert, NFKC-normalized lowercase text with Markdown removed.

    Link labels and code contents are retained, while link targets, HTML tags,
    comments, and Markdown punctuation are removed. No renderer, HTML engine,
    translator, stemmer, or code executor is involved.
    """

    normalized = unicodedata.normalize("NFKC", text)
    normalized = _HTML_COMMENT.sub(" ", normalized)
    normalized = _AUTOLINK.sub(" ", normalized)
    normalized = _IMAGE.sub(r" \1 ", normalized)
    normalized = _LINK.sub(r" \1 ", normalized)
    normalized = _REFERENCE_LINK.sub(r" \1 ", normalized)
    normalized = _INLINE_CODE.sub(r" \1 ", normalized)
    normalized = _remove_fence_markers(normalized)
    normalized = _HTML_TAG.sub(" ", normalized)
    normalized = html.unescape(normalized)
    normalized = _strip_markdown_line_prefixes(normalized)
    normalized = normalized.replace("\\", "")
    normalized = normalized.replace("*", "").replace("~", "")
    normalized = _WHITESPACE.sub(" ", normalized).strip()
    return _SPACE_BEFORE_PUNCTUATION.sub(r"\1", normalized).lower()


def tokenize(text: str) -> tuple[str, ...]:
    """Tokenize normalized text while preserving common technical compounds."""

    return tuple(TOKEN_PATTERN.findall(normalize_lexical_text(text)))


def partition_markdown_body(body_text: str) -> tuple[tuple[str, ...], str]:
    """Return normalized headings and normalized non-heading body text.

    ATX and Setext headings outside fenced code blocks are separated so the
    unweighted combined document contains each heading once rather than once in
    ``heading_text`` and again in ``body_text``.
    """

    headings: list[str] = []
    body_lines: list[str] = []
    lines = body_text.splitlines()
    fence_character: str | None = None
    fence_length = 0
    index = 0

    while index < len(lines):
        line = lines[index]
        fence = _FENCE.match(line)
        if fence is not None:
            marker = fence.group(1)
            character = marker[0]
            if fence_character is None:
                fence_character = character
                fence_length = len(marker)
            elif character == fence_character and len(marker) >= fence_length:
                fence_character = None
                fence_length = 0
            body_lines.append(line)
            index += 1
            continue

        if fence_character is None:
            atx = _ATX_HEADING.match(line)
            if atx is not None:
                heading = normalize_lexical_text(atx.group(1))
                if heading:
                    headings.append(heading)
                index += 1
                continue

            if index + 1 < len(lines) and _SETEXT_UNDERLINE.match(lines[index + 1]):
                heading = normalize_lexical_text(line)
                if heading:
                    headings.append(heading)
                index += 2
                continue

        body_lines.append(line)
        index += 1

    return tuple(headings), normalize_lexical_text("\n".join(body_lines))


def _remove_fence_markers(text: str) -> str:
    return "\n".join("" if _FENCE.match(line) else line for line in text.splitlines())


def _strip_markdown_line_prefixes(text: str) -> str:
    lines: list[str] = []
    for line in text.splitlines():
        line = _ATX_HEADING.sub(r"\1", line)
        line = _BLOCK_PREFIX.sub("", line)
        if _SETEXT_UNDERLINE.match(line):
            continue
        lines.append(line)
    return "\n".join(lines)
