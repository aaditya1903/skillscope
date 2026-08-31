"""Versioned safe skill-detail endpoint."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from skillscope.api.dependencies import get_api_service, get_db_session
from skillscope.api.errors import ApiError, request_id_from
from skillscope.api.routes.common import error_responses
from skillscope.api.schemas import SkillDetailResponse
from skillscope.api.service import (
    ApiServiceUnavailableError,
    SkillNotFoundError,
    SkillScopeApiService,
)

router = APIRouter(prefix="/api/v1", tags=["skills"])
DbSession = Annotated[Session, Depends(get_db_session)]
ApiService = Annotated[SkillScopeApiService, Depends(get_api_service)]


@router.get(
    "/skills/{skill_id}",
    response_model=SkillDetailResponse,
    responses=error_responses(404, 422, 503),
    summary="Get safe stored skill detail",
)
def skill_detail(
    skill_id: UUID,
    request: Request,
    session: DbSession,
    service: ApiService,
) -> SkillDetailResponse:
    """Return metadata, structural signals, and a bounded plain-text excerpt."""

    try:
        return service.skill_detail(
            session,
            request_id=request_id_from(request),
            skill_id=skill_id,
        )
    except SkillNotFoundError as error:
        raise ApiError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="skill_not_found",
            message="The requested skill was not found.",
        ) from error
    except ApiServiceUnavailableError as error:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="skill_detail_unavailable",
            message="Skill detail is temporarily unavailable.",
        ) from error
