"""Schemas shared by API routes."""

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Response returned by the liveness endpoint."""

    status: Literal["ok"] = "ok"
    service: str
    version: str
