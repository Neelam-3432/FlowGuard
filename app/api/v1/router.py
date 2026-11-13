"""API v1 router aggregator."""

from fastapi import APIRouter
from app.api.v1.endpoints import health

api_router = APIRouter()

# Include endpoint sub-routers
api_router.include_router(health.router)

