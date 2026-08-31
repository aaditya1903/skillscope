"""Versioned retrieval-evaluation evidence endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from skillscope.api.dependencies import get_api_service
from skillscope.api.errors import ApiError, request_id_from
from skillscope.api.routes.common import error_responses
from skillscope.api.schemas import LatestEvaluationResponse
from skillscope.api.service import ApiServiceUnavailableError, SkillScopeApiService

router = APIRouter(prefix="/api/v1", tags=["evaluation"])
ApiService = Annotated[SkillScopeApiService, Depends(get_api_service)]


@router.get(
    "/evaluations/latest",
    response_model=LatestEvaluationResponse,
    responses=error_responses(503),
    summary="Get the latest completed retrieval evaluation",
)
def latest_evaluation(
    request: Request,
    service: ApiService,
) -> LatestEvaluationResponse:
    """Return aggregate metrics from the canonical locked test comparison."""

    try:
        return service.latest_evaluation(request_id=request_id_from(request))
    except ApiServiceUnavailableError as error:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="evaluation_unavailable",
            message="Evaluation evidence is temporarily unavailable.",
        ) from error
