"""Shared OpenAPI response declarations for versioned routes."""

from typing import Any

from skillscope.api.schemas import ErrorResponse


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """Describe the structured error envelope without duplicating schemas."""

    return {
        status_code: {
            "model": ErrorResponse,
            "description": _description(status_code),
        }
        for status_code in status_codes
    }


def _description(status_code: int) -> str:
    return {
        400: "Invalid request semantics",
        404: "Resource not found",
        422: "Request schema validation failed",
        429: "Retrieval capacity is temporarily exhausted",
        500: "Unexpected internal failure",
        503: "A required dependency is unavailable or stale",
    }.get(status_code, "Structured API error")
