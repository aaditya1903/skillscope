"""FastAPI application factory."""

from fastapi import FastAPI

from skillscope.api.routes.health import router as health_router
from skillscope.core.config import get_settings
from skillscope.core.logging import configure_logging


def create_app() -> FastAPI:
    """Create an application instance with explicit, testable wiring."""
    settings = get_settings()
    configure_logging(settings.log_level)

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Discover and evaluate public Agent Skills.",
    )
    application.include_router(health_router)
    return application


app = create_app()
