"""Structured decision output models for FlowGuard Rules Engine."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RuleEvaluationResult(BaseModel):
    """Detailed result for an individual evaluated rule."""

    rule_id: str = Field(..., description="Unique rule identifier")
    category: str = Field(..., description="Category of the evaluated rule (mandatory, threshold, conditional, group)")
    passed: bool = Field(..., description="Whether the rule passed evaluation")
    reason: str = Field(..., description="Human-readable explanation of the evaluation outcome")
    field: Optional[str] = Field(None, description="Primary field evaluated, if applicable")
    operator: Optional[str] = Field(None, description="Operator applied, if applicable")
    expected_value: Optional[Any] = Field(None, description="Expected value or threshold, if applicable")
    trace: Optional[Dict[str, Any]] = Field(None, description="Execution trace details without sensitive values")


class DecisionResult(BaseModel):
    """Aggregated decision result containing overall outcome, statistics, and traces."""

    status: str = Field(..., description="Overall decision status ('approved' or 'rejected')")
    passed: bool = Field(..., description="Boolean indicating whether all required rules passed")
    total_rules: int = Field(..., description="Total number of evaluated rules")
    passed_rules: int = Field(..., description="Number of rules that passed")
    failed_rules: int = Field(..., description="Number of rules that failed")
    results: List[RuleEvaluationResult] = Field(..., description="Sequential individual rule evaluation results")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Execution metadata and timestamps")

