"""Inert demonstration script. SkillScope records its metadata and never runs it."""

from __future__ import annotations


def has_text_layer(page_characters: int) -> bool:
    """Report whether a page carries enough characters to skip OCR."""

    return page_characters > 32
