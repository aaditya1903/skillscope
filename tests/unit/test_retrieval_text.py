"""Unit coverage for inert lexical text processing."""

from skillscope.retrieval.text import (
    TOKEN_PATTERN_TEXT,
    normalize_lexical_text,
    partition_markdown_body,
    tokenize,
)


def test_normalization_is_nfkc_lowercase_and_whitespace_stable() -> None:
    source = "Ｆｕｌｌ　Ｗｉｄｔｈ\n\tTEXT"  # noqa: RUF001

    assert normalize_lexical_text(source) == "full width text"


def test_markdown_is_stripped_without_losing_labels_or_code() -> None:
    source = "# Heading\nUse **`uv sync`** and [the guide](https://example.com)."

    assert normalize_lexical_text(source) == "heading use uv sync and the guide."


def test_html_is_inert_and_tags_comments_and_autolinks_are_removed() -> None:
    source = "<!-- hidden --><strong>Keep me</strong> <https://example.com>"

    normalized = normalize_lexical_text(source)

    assert normalized == "keep me"
    assert "strong" not in normalized


def test_tokenizer_preserves_common_technical_compounds() -> None:
    tokens = tokenize("SKILL.md C++ C# CI/CD scikit-learn node.js foo_bar naïve")

    assert tokens == (
        "skill.md",
        "c++",
        "c#",
        "ci/cd",
        "scikit-learn",
        "node.js",
        "foo_bar",
        "naïve",
    )


def test_partition_separates_atx_and_setext_headings_once() -> None:
    headings, body = partition_markdown_body(
        "# Install\nRun uv sync.\n\nUsage\n-----\nCall the tool."
    )

    assert headings == ("install", "usage")
    assert body == "run uv sync. call the tool."


def test_partition_does_not_treat_fenced_code_as_a_heading() -> None:
    headings, body = partition_markdown_body("```md\n# Example only\n```\n# Real heading")

    assert headings == ("real heading",)
    assert "example only" in body


def test_token_pattern_is_explicit_for_documentation() -> None:
    assert TOKEN_PATTERN_TEXT == r"[^\W_]+(?:(?:[./:_-][^\W_]+)|(?:\+\+|\+|#))*"
