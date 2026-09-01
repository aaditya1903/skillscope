"""Inert demonstration script. SkillScope records its metadata and never runs it."""

from __future__ import annotations


def subtotal(rows: list[dict[str, float]], key: str) -> float:
    """Return the sum of one numeric column."""

    return sum(row.get(key, 0.0) for row in rows)
