"""Pydantic schemas for Application submission and responses."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ApplicationCreateRequest(BaseModel):
    """Payload submitted to process an application through a workflow."""

    workflow_id: str = Field(..., min_length=1, description="Identifier of the workflow to execute")
    idempotency_key: str = Field(..., min_length=1, description="Client-provided idempotency key")
    input_data: Dict[str, Any] = Field(..., description="Application input payload to evaluate")
    request_id: Optional[str] = Field(None, description="Optional request tracking identifier")
    workflow_version: Optional[int] = Field(None, description="Specific workflow version to execute (defaults to active version)")


class RuleSummaryResponse(BaseModel):
    """Summary of an individual rule evaluation result for API responses."""

    rule_id: str = Field(..., description="Unique rule identifier")
    category: str = Field(..., description="Rule category")
    passed: bool = Field(..., description="Evaluation outcome")
    reason: str = Field(..., description="Human-readable outcome description")


class DecisionSummaryResponse(BaseModel):
    """Structured decision outcome summary for API responses."""

    status: str = Field(..., description="Overall decision status ('approved' or 'rejected')")
    passed: bool = Field(..., description="Whether the application passed all rules")
    total_rules: int = Field(..., description="Total evaluated rules")
    passed_rules: int = Field(..., description="Passed rules count")
    failed_rules: int = Field(..., description="Failed rules count")
    results: List[RuleSummaryResponse] = Field(default_factory=list, description="Per-rule evaluation results")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Evaluation metadata")


class ApplicationResponse(BaseModel):
    """API response model representing a processed workflow application."""

    id: int = Field(..., description="Application database ID")
    request_id: str = Field(..., description="Request tracking identifier")
    workflow_id: str = Field(..., description="Workflow identifier")
    workflow_config_id: int = Field(..., description="Workflow configuration database ID")
    workflow_version: int = Field(..., description="Workflow configuration version executed")
    idempotency_key: str = Field(..., description="Idempotency key")
    status: str = Field(..., description="Current application status (APPROVED, REJECTED, RETRY_PENDING, MANUAL_REVIEW, FAILED)")
    retry_count: int = Field(0, description="Number of retry attempts executed")
    verification_outcome: Optional[str] = Field(None, description="External verification outcome")
    failure_reason: Optional[str] = Field(None, description="Failure reason description if applicable")
    decision: Optional[DecisionSummaryResponse] = Field(None, description="Detailed decision result")
    created_at: datetime = Field(..., description="Submission timestamp")
    updated_at: datetime = Field(..., description="Last update timestamp")
