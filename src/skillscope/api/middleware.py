"""Request correlation, safe access logs, and response hardening."""

from __future__ import annotations

import logging
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

logger = logging.getLogger(__name__)


def install_request_middleware(application: FastAPI) -> None:
    """Install one request-ID boundary without logging URLs or query values."""

    @application.middleware("http")
    async def request_context(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        request_id = uuid4().hex
        request.state.request_id = request_id
        started_at = perf_counter()

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        elapsed_ms = (perf_counter() - started_at) * 1_000.0
        logger.info(
            "api_request_complete",
            extra={
                "request_id": request_id,
                "http_method": request.method,
                "http_status": response.status_code,
                "duration_ms": round(elapsed_ms, 3),
            },
        )
        return response
