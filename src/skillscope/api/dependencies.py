"""Request-scoped database and bounded search dependencies."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
from threading import BoundedSemaphore
from typing import cast

from fastapi import Request
from sqlalchemy.orm import Session

from skillscope.api.service import SkillScopeApiService
from skillscope.core.config import Settings
from skillscope.db.session import get_session_factory


def get_db_session() -> Iterator[Session]:
    """Yield one read-only request-scoped SQLAlchemy session."""

    with get_session_factory()() as session:
        yield session


def get_app_settings(request: Request) -> Settings:
    """Return the immutable settings selected by the application factory."""

    return cast(Settings, request.app.state.settings)


@lru_cache(maxsize=1)
def get_api_service() -> SkillScopeApiService:
    """Return the stateless API service with lazily loaded retrieval assets."""

    return SkillScopeApiService()


class SearchCapacity:
    """Reject excess concurrent retrieval instead of building an unbounded queue."""

    def __init__(self, maximum_concurrency: int = 5) -> None:
        if not 1 <= maximum_concurrency <= 100:
            raise ValueError("maximum_concurrency must be between 1 and 100")
        self._semaphore = BoundedSemaphore(maximum_concurrency)

    def acquire(self) -> bool:
        """Acquire immediately or report capacity exhaustion."""

        return self._semaphore.acquire(blocking=False)

    def release(self) -> None:
        """Release one acquired retrieval slot."""

        self._semaphore.release()


@lru_cache(maxsize=1)
def get_search_capacity() -> SearchCapacity:
    """Return one process-wide bounded retrieval gate."""

    return SearchCapacity()
