"""Pydantic schemas for rule configuration validation in FlowGuard."""

from typing import Annotated, Any, List, Literal, Optional, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from app.rules.exceptions import RuleConfigurationError
from app.rules.operators import is_valid_operator


def _validate_conditions_depth(conditions: List[Any], current_depth: int = 1) -> None:
    """Recursively check that condition nesting does not exceed the maximum allowed depth of 3."""
    if current_depth > 3:
        raise ValueError("ConditionGroup exceeds maximum nesting depth limit of 3.")
    for cond in conditions:
        if isinstance(cond, ConditionGroup):
            _validate_conditions_depth(cond.conditions, current_depth + 1)
        elif isinstance(cond, dict) and "conditions" in cond:
            _validate_conditions_depth(cond["conditions"], current_depth + 1)


class SimpleCondition(BaseModel):
    """Atomic condition comparing an application field against an expected value."""

    field: str = Field(..., min_length=1, description="Application field to inspect")
    operator: str = Field(..., description="Whitelisted comparison operator")
    value: Optional[Any] = Field(default=None, description="Expected value or operand")

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if not is_valid_operator(v):
            raise ValueError(f"Operator '{v}' is not in the approved whitelist.")
        return v


class ConditionGroup(BaseModel):
    """Bounded recursive group of conditions combined via AND / OR logic."""

    combinator: Literal["AND", "OR"] = Field("AND", description="Logical combinator for conditions")
    conditions: List[Union[SimpleCondition, "ConditionGroup"]] = Field(
        ..., min_length=1, description="List of conditions or nested groups"
    )

    @model_validator(mode="after")
    def validate_nesting_depth(self) -> "ConditionGroup":
        _validate_conditions_depth(self.conditions, current_depth=1)
        return self


class MandatoryRule(BaseModel):
    """Rule verifying that a mandatory field exists and is not null/empty."""

    rule_id: str = Field(..., min_length=1, description="Unique identifier for the rule")
    category: Literal["mandatory"] = "mandatory"
    field: str = Field(..., min_length=1, description="Mandatory field name")
    description: Optional[str] = Field(None, description="Human-readable rule explanation")
    allow_empty_string: bool = Field(False, description="Whether an empty string is permissible")


class ThresholdRule(BaseModel):
    """Rule evaluating a numeric field against a threshold."""

    rule_id: str = Field(..., min_length=1, description="Unique identifier for the rule")
    category: Literal["threshold"] = "threshold"
    field: str = Field(..., min_length=1, description="Numeric field name")
    operator: Literal["gt", "gte", "lt", "lte", "eq", "ne"] = Field(
        ..., description="Numeric comparison operator"
    )
    threshold: Union[int, float] = Field(..., description="Numeric threshold value")
    description: Optional[str] = Field(None, description="Human-readable rule explanation")

    @field_validator("threshold", mode="before")
    @classmethod
    def validate_numeric_threshold(cls, v: Any) -> Union[int, float]:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"Threshold must be numeric (int or float), got {type(v).__name__}")
        return v


class ConditionalRule(BaseModel):
    """Rule with an antecedent condition (when) and a consequent assertion (then)."""

    rule_id: str = Field(..., min_length=1, description="Unique identifier for the rule")
    category: Literal["conditional"] = "conditional"
    when: Union[SimpleCondition, ConditionGroup] = Field(..., description="Antecedent condition")
    then: Union[SimpleCondition, ConditionGroup] = Field(..., description="Assertion evaluated when condition is met")
    description: Optional[str] = Field(None, description="Human-readable rule explanation")


class GroupRule(BaseModel):
    """Composite rule combining multiple conditions using AND / OR combinators."""

    rule_id: str = Field(..., min_length=1, description="Unique identifier for the rule")
    category: Literal["group"] = "group"
    combinator: Literal["AND", "OR"] = Field("AND", description="Logical combinator")
    conditions: List[Union[SimpleCondition, ConditionGroup]] = Field(
        ..., min_length=1, description="List of conditions to evaluate"
    )
    description: Optional[str] = Field(None, description="Human-readable rule explanation")

    @model_validator(mode="after")
    def validate_nesting_depth(self) -> "GroupRule":
        _validate_conditions_depth(self.conditions, current_depth=1)
        return self


# Discriminated union of all supported rule types
Rule = Annotated[
    Union[MandatoryRule, ThresholdRule, ConditionalRule, GroupRule],
    Field(discriminator="category"),
]


class RulesConfig(BaseModel):
    """Top-level container for a collection of configured rules."""

    rules: List[Rule] = Field(default_factory=list, description="Ordered list of rules")
    version: Optional[Union[str, int]] = Field(None, description="Configuration version")
    description: Optional[str] = Field(None, description="Workflow configuration description")


def load_rules_config(data: Union[RulesConfig, dict[str, Any], list[Any]]) -> RulesConfig:
    """Parse and validate rules configuration from dict, list, or RulesConfig instance.

    Raises RuleConfigurationError if configuration is invalid.
    """
    if isinstance(data, RulesConfig):
        return data

    if isinstance(data, list):
        data = {"rules": data}

    if not isinstance(data, dict):
        raise RuleConfigurationError(
            f"Expected dict or list for rules configuration, got {type(data).__name__}"
        )

    try:
        return RulesConfig.model_validate(data)
    except Exception as e:
        raise RuleConfigurationError(f"Invalid rule configuration: {e}") from e
