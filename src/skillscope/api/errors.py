"""Structured, non-leaking HTTP error handling."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status

from skillscope.api.schemas import ErrorDetail, ErrorField, ErrorResponse

logger = logging.getLogger(__name__)


class ApiError(RuntimeError):
    """A deliberate public API failure with a safe client-facing message."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = dict(headers or {})


def request_id_from(request: Request) -> str:
    """Return middleware state without trusting a caller-provided identifier."""

    value = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else "unavailable"


def install_error_handlers(application: FastAPI) -> None:
    """Register one stable error envelope for expected and unexpected failures."""

    application.add_exception_handler(ApiError, _api_error_handler)
    application.add_exception_handler(RequestValidationError, _validation_error_handler)
    application.add_exception_handler(Exception, _unexpected_error_handler)


async def _api_error_handler(request: Request, error: Exception) -> JSONResponse:
    assert isinstance(error, ApiError)
    return _error_response(
        request,
        status_code=error.status_code,
        code=error.code,
        message=error.message,
        headers=error.headers,
    )


async def _validation_error_handler(
    request: Request,
    error: Exception,
) -> JSONResponse:
    assert isinstance(error, RequestValidationError)
    fields = tuple(_safe_validation_field(item) for item in error.errors())
    return _error_response(
        request,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        code="request_validation_failed",
        message="The request parameters are invalid.",
        fields=fields,
    )


async def _unexpected_error_handler(request: Request, error: Exception) -> JSONResponse:
    logger.error(
        "api_unexpected_error",
        extra={"request_id": request_id_from(request)},
    )
    return _error_response(
        request,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        code="internal_error",
        message="The request could not be completed.",
    )


def _safe_validation_field(item: dict[str, Any]) -> ErrorField:
    location = item.get("loc", ())
    safe_parts = [
        str(part)
        for part in location
        if isinstance(part, str | int) and str(part) not in {"query", "path", "body"}
    ]
    raw_type = item.get("type")
    code = str(raw_type) if isinstance(raw_type, str) else "invalid"
    return ErrorField(
        field=".".join(safe_parts) or "request",
        code=code,
        message=_validation_message(code),
    )


def _validation_message(code: str) -> str:
    if code == "missing":
        return "This field is required."
    if code in {"enum", "literal_error"}:
        return "Use one of the documented values."
    if code in {"greater_than_equal", "greater_than", "too_short", "string_too_short"}:
        return "The value is below the documented minimum."
    if code in {"less_than_equal", "less_than", "too_long", "string_too_long"}:
        return "The value is above the documented maximum."
    if code in {"uuid_parsing", "uuid_type"}:
        return "Use a valid UUID."
    return "Use a value matching the documented schema."


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    fields: tuple[ErrorField, ...] = (),
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        request_id=request_id_from(request),
        error=ErrorDetail(code=code, message=message, fields=fields),
    )
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers=dict(headers or {}),
    )
