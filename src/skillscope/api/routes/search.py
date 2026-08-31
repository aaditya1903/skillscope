"""Versioned frozen-corpus search endpoint."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from skillscope.api.dependencies import (
    SearchCapacity,
    get_api_service,
    get_db_session,
    get_search_capacity,
)
from skillscope.api.errors import ApiError, request_id_from
from skillscope.api.routes.common import error_responses
from skillscope.api.schemas import SearchResponse
from skillscope.api.service import ApiServiceUnavailableError, SkillScopeApiService
from skillscope.db.enums import LicenseStatus, RetrievalMethod, ValidationStatus
from skillscope.retrieval.filters import RetrievalFilters

router = APIRouter(prefix="/api/v1", tags=["search"])
DbSession = Annotated[Session, Depends(get_db_session)]
ApiService = Annotated[SkillScopeApiService, Depends(get_api_service)]
Capacity = Annotated[SearchCapacity, Depends(get_search_capacity)]


@router.get(
    "/search",
    response_model=SearchResponse,
    responses=error_responses(400, 422, 429, 503),
    summary="Search the frozen Agent Skills corpus",
)
def search(
    request: Request,
    session: DbSession,
    service: ApiService,
    capacity: Capacity,
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=500,
            description="Task-oriented query; leading and trailing whitespace is ignored.",
        ),
    ],
    mode: RetrievalMethod = RetrievalMethod.BM25,
    limit: Annotated[int, Query(ge=1, le=50)] = 10,
    license_status: LicenseStatus | None = None,
    validation_status: ValidationStatus | None = None,
    has_scripts: bool | None = None,
) -> SearchResponse:
    """Rank skills with BM25 by default or explicit dense/hybrid retrieval."""

    normalized_query = q.strip()
    if not normalized_query:
        raise ApiError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="empty_query",
            message="The query must contain a non-whitespace character.",
        )
    if not capacity.acquire():
        raise ApiError(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            code="search_capacity_exhausted",
            message="Search capacity is temporarily exhausted; retry shortly.",
            headers={"Retry-After": "1"},
        )
    try:
        return service.search(
            session,
            request_id=request_id_from(request),
            query=normalized_query,
            mode=mode,
            limit=limit,
            filters=RetrievalFilters(
                license_statuses=(None if license_status is None else frozenset({license_status})),
                validation_statuses=(
                    None if validation_status is None else frozenset({validation_status})
                ),
                has_scripts=has_scripts,
            ),
        )
    except ApiServiceUnavailableError as error:
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code="retrieval_unavailable",
            message="The frozen retrieval service is unavailable.",
        ) from error
    finally:
        capacity.release()
