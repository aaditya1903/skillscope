"""Conservative validation for values used to construct GitHub API requests."""

from __future__ import annotations

import re
from urllib.parse import unquote, urlsplit

GITHUB_API_HOST = "api.github.com"
GITHUB_HTML_HOST = "github.com"

_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_GIT_OBJECT_SHA_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_REF_FORBIDDEN_CHARACTERS = frozenset({" ", "~", "^", ":", "?", "*", "[", "\\"})


def _validate_clean_text(value: str, *, field: str) -> str:
    if not value or value != value.strip():
        raise ValueError(f"{field} must be non-empty and have no surrounding whitespace")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"{field} contains a control character")
    return value


def validate_owner(value: str) -> str:
    """Return a conservative GitHub owner login or raise ``ValueError``."""
    value = _validate_clean_text(value, field="owner")
    if not _OWNER_PATTERN.fullmatch(value) or "--" in value:
        raise ValueError("owner must be 1-39 alphanumeric or single-hyphen characters")
    return value


def validate_repository_name(value: str) -> str:
    """Return a conservative GitHub repository name or raise ``ValueError``."""
    value = _validate_clean_text(value, field="repository")
    if not _REPOSITORY_PATTERN.fullmatch(value) or ".." in value or value.endswith("."):
        raise ValueError("repository contains unsupported characters or dot sequences")
    return value


def validate_repository_full_name(value: str) -> str:
    """Validate an ``owner/repository`` identifier."""
    value = _validate_clean_text(value, field="repository full name")
    parts = value.split("/")
    if len(parts) != 2:
        raise ValueError("repository full name must contain exactly one slash")
    validate_owner(parts[0])
    validate_repository_name(parts[1])
    return value


def validate_relative_path(value: str) -> str:
    """Validate a non-empty, repository-relative POSIX path."""
    value = _validate_clean_text(value, field="path")
    if len(value.encode("utf-8")) > 4096:
        raise ValueError("path exceeds 4096 UTF-8 bytes")
    if value.startswith("/") or value.endswith("/"):
        raise ValueError("path must be relative and have no trailing slash")
    if "\\" in value or "%" in value:
        raise ValueError("path contains a backslash or encoded component")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError("path contains an empty, current, or parent component")
    return value


def validate_git_ref(value: str) -> str:
    """Validate a conservative branch, tag, or commit reference."""
    value = _validate_clean_text(value, field="ref")
    if len(value.encode("utf-8")) > 255:
        raise ValueError("ref exceeds 255 UTF-8 bytes")
    if value == "@" or value.startswith("/") or value.endswith(("/", ".")):
        raise ValueError("ref has an unsupported boundary")
    if any(character in _REF_FORBIDDEN_CHARACTERS for character in value):
        raise ValueError("ref contains a forbidden character")
    if ".." in value or "@{" in value or "//" in value:
        raise ValueError("ref contains a forbidden sequence")
    parts = value.split("/")
    if any(part.startswith(".") or part.endswith(".lock") for part in parts):
        raise ValueError("ref contains a forbidden component")
    return value


def validate_git_object_sha(value: str) -> str:
    """Validate a full SHA-1 or SHA-256 Git object identifier."""
    value = _validate_clean_text(value, field="Git object SHA")
    if not _GIT_OBJECT_SHA_PATTERN.fullmatch(value):
        raise ValueError("Git object SHA must be 40 or 64 lowercase hexadecimal characters")
    return value


def _validate_github_url(value: str, *, expected_host: str) -> str:
    value = _validate_clean_text(value, field="URL")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError("URL is malformed") from error

    if parsed.scheme != "https" or parsed.hostname != expected_host:
        raise ValueError(f"URL must use HTTPS on {expected_host}")
    if parsed.username is not None or parsed.password is not None or port is not None:
        raise ValueError("URL must not contain credentials or an explicit port")
    if parsed.fragment:
        raise ValueError("URL must not contain a fragment")
    if any(part in {".", ".."} for part in unquote(parsed.path).split("/")):
        raise ValueError("URL path contains traversal")
    return value


def validate_github_api_url(value: str) -> str:
    """Validate an allowlisted GitHub API URL."""
    return _validate_github_url(value, expected_host=GITHUB_API_HOST)


def validate_github_html_url(value: str) -> str:
    """Validate an allowlisted public GitHub HTML URL."""
    return _validate_github_url(value, expected_host=GITHUB_HTML_HOST)
