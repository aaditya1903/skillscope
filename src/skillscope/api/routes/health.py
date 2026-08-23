"""Liveness endpoint."""

from fastapi import APIRouter

from skillscope.api.schemas import HealthResponse
from skillscope.core.config import get_settings

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthResponse, summary="Check process liveness")
async def healthz() -> HealthResponse:
    """Return process liveness without checking external dependencies."""
    settings = get_settings()
    return HealthResponse(service=settings.app_name, version=settings.app_version)
