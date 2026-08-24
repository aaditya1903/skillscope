"""Rate-limit metadata parsed from GitHub REST response headers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime


def _parse_non_negative_int(headers: Mapping[str, str], name: str) -> int | None:
    value = headers.get(name)
    if value is None:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _parse_reset_at(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    try:
        return datetime.fromtimestamp(timestamp, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class GitHubRateLimitSnapshot:
    """Rate-limit state carried by one GitHub response."""

    limit: int | None
    used: int | None
    remaining: int | None
    reset_at: datetime | None
    resource: str | None
    retry_after_seconds: int | None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> GitHubRateLimitSnapshot:
        """Parse known headers without failing on absent or malformed values."""
        normalized = {name.casefold(): value for name, value in headers.items()}
        reset_timestamp = _parse_non_negative_int(normalized, "x-ratelimit-reset")
        resource = normalized.get("x-ratelimit-resource")

        return cls(
            limit=_parse_non_negative_int(normalized, "x-ratelimit-limit"),
            used=_parse_non_negative_int(normalized, "x-ratelimit-used"),
            remaining=_parse_non_negative_int(normalized, "x-ratelimit-remaining"),
            reset_at=_parse_reset_at(reset_timestamp),
            resource=resource.strip() if resource and resource.strip() else None,
            retry_after_seconds=_parse_non_negative_int(normalized, "retry-after"),
        )

    @property
    def exhausted(self) -> bool:
        """Return whether GitHub explicitly reports no remaining requests."""
        return self.remaining == 0

    def retry_delay_seconds(self, *, now: datetime | None = None) -> float | None:
        """Return GitHub's requested delay for a rate-limited response."""
        if self.retry_after_seconds is not None:
            return float(self.retry_after_seconds)
        if not self.exhausted or self.reset_at is None:
            return None

        current_time = now or datetime.now(UTC)
        return max(0.0, (self.reset_at - current_time).total_seconds())
