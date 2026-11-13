"""Pydantic schemas for health check responses."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    """Health check response payload schema."""

    status: str = Field(..., description="Operational status of the service", examples=["ok"])
    app_name: str = Field(..., description="Application name", examples=["FlowGuard"])
    version: str = Field(..., description="Semantic version of the application", examples=["0.1.0"])

