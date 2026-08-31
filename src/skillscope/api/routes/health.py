"""Liveness endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends

from skillscope.api.dependencies import get_app_settings
from skillscope.api.schemas import HealthResponse
from skillscope.core.config import Settings

router = APIRouter(tags=["health"])
AppSettings = Annotated[Settings, Depends(get_app_settings)]


@router.get("/healthz", response_model=HealthResponse, summary="Check process liveness")
async def healthz(settings: AppSettings) -> HealthResponse:
    """Return process liveness without checking external dependencies."""
    return HealthResponse(service=settings.app_name, version=settings.app_version)
