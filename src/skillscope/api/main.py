"""FastAPI application factory."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from skillscope.api.errors import install_error_handlers
from skillscope.api.middleware import install_request_middleware
from skillscope.api.routes.evaluations import router as evaluations_router
from skillscope.api.routes.health import router as health_router
from skillscope.api.routes.readiness import router as readiness_router
from skillscope.api.routes.search import router as search_router
from skillscope.api.routes.skills import router as skills_router
from skillscope.api.routes.stats import router as stats_router
from skillscope.core.config import Settings, get_settings
from skillscope.core.logging import configure_logging


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance with explicit, testable wiring."""
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    application = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        description=(
            "Search a frozen, validated public Agent Skills corpus using transparent "
            "BM25, exact dense retrieval, or reciprocal-rank fusion."
        ),
        contact={
            "name": "SkillScope project",
            "url": "https://github.com/aaditya1903/skillscope",
        },
        license_info={"name": "MIT"},
    )
    application.state.settings = resolved_settings
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[resolved_settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Accept", "Content-Type"],
        max_age=600,
    )
    install_request_middleware(application)
    install_error_handlers(application)
    application.include_router(health_router)
    application.include_router(readiness_router)
    application.include_router(search_router)
    application.include_router(skills_router)
    application.include_router(stats_router)
    application.include_router(evaluations_router)
    return application


app = create_app()
