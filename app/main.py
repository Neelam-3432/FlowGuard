"""FastAPI application factory and instance definition."""

from fastapi import FastAPI
from app.api.v1.endpoints.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import settings


def create_application() -> FastAPI:
    """Create and configure the FastAPI application instance."""
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=settings.app_description,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # Root-level health endpoint (GET /health)
    app.include_router(health_router)

    # API v1 routes (GET /api/v1/health and future v1 endpoints)
    app.include_router(api_router, prefix=settings.api_v1_str)

    return app


app: FastAPI = create_application()

