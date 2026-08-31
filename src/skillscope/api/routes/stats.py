"""Versioned observatory statistics endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from skillscope.api.dependencies import get_api_service, get_db_session
from skillscope.api.errors import ApiError, request_id_from
from skillscope.api.routes.common import error_responses
from skillscope.api.schemas import StatsResponse
from skillscope.api.service import ApiServiceUnavailableError, SkillScopeApiService

router = APIRouter(prefix="/api/v1", tags=["statistics"])
DbSession = Annotated[Session, Depends(get_db_session)]
ApiService = Annotated[SkillScopeApiService, Depends(get_api_service)]


@router.get(
    "/stats",
    response_model=StatsResponse,
    responses=error_responses(503),
    summary="Get aggregate corpus statistics",
)
def stats(
    request: Request,
    session: DbSession,
    service: ApiService,
) -> StatsResponse:
    """Return current database counts tied to the frozen retrieval snapshot."""

    try:
        return service.stats(session, request_id=request_id_from(request))
    except ApiServiceUnavailableError as error:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="statistics_unavailable",
            message="Corpus statistics are temporarily unavailable.",
        ) from error
