"""Database- and retrieval-aware readiness endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from skillscope.api.dependencies import get_api_service, get_app_settings, get_db_session
from skillscope.api.schemas import ReadinessResponse
from skillscope.api.service import SkillScopeApiService
from skillscope.core.config import Settings

router = APIRouter(tags=["health"])
DbSession = Annotated[Session, Depends(get_db_session)]
ApiService = Annotated[SkillScopeApiService, Depends(get_api_service)]
AppSettings = Annotated[Settings, Depends(get_app_settings)]


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={
        503: {
            "model": ReadinessResponse,
            "description": "Database, frozen corpus, embeddings, or model runtime is not ready",
        }
    },
    summary="Check retrieval readiness",
)
def readyz(
    response: Response,
    session: DbSession,
    service: ApiService,
    settings: AppSettings,
) -> ReadinessResponse:
    """Report external readiness separately from process liveness."""

    ready, checks = service.readiness(session)
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "not_ready",
        service=settings.app_name,
        version=settings.app_version,
        checks=checks,
    )
