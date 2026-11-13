"""FlowGuard Rules Engine package."""

from app.rules.decision import DecisionResult, RuleEvaluationResult
from app.rules.evaluator import RulesEvaluator, evaluate_rules
from app.rules.exceptions import (
    EvaluationError,
    InvalidOperandError,
    RuleConfigurationError,
    RulesEngineError,
    UnsupportedOperatorError,
)
from app.rules.operators import (
    ALLOWED_OPERATORS,
    OPERATOR_REGISTRY,
    apply_operator,
    is_valid_operator,
)
from app.rules.schemas import (
    ConditionalRule,
    ConditionGroup,
    GroupRule,
    MandatoryRule,
    Rule,
    RulesConfig,
    SimpleCondition,
    ThresholdRule,
    load_rules_config,
)

__all__ = [
    "RulesEvaluator",
    "evaluate_rules",
    "DecisionResult",
    "RuleEvaluationResult",
    "RulesConfig",
    "Rule",
    "MandatoryRule",
    "ThresholdRule",
    "ConditionalRule",
    "GroupRule",
    "SimpleCondition",
    "ConditionGroup",
    "load_rules_config",
    "ALLOWED_OPERATORS",
    "OPERATOR_REGISTRY",
    "apply_operator",
    "is_valid_operator",
    "RulesEngineError",
    "RuleConfigurationError",
    "UnsupportedOperatorError",
    "InvalidOperandError",
    "EvaluationError",
]

