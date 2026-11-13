"""Deterministic Rules Evaluator for FlowGuard."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple, Union
from app.rules.decision import DecisionResult, RuleEvaluationResult
from app.rules.exceptions import EvaluationError
from app.rules.operators import MISSING, apply_operator
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


def get_field_value(data: Dict[str, Any], field_path: str) -> Any:
    """Retrieve a value from application data supporting both flat and dot-notated paths.

    Returns MISSING sentinel if the key does not exist.
    """
    if field_path in data:
        return data[field_path]

    # Check dot-notated paths for nested structures (e.g., 'applicant.age')
    parts = field_path.split(".")
    current: Any = data
    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return MISSING
    return current


class RulesEvaluator:
    """Deterministic, pure-python evaluation engine for configured workflow rules."""

    def __init__(self, config: Union[RulesConfig, Dict[str, Any], List[Any]]) -> None:
        self.config: RulesConfig = load_rules_config(config)

    def evaluate(self, application_data: Dict[str, Any]) -> DecisionResult:
        """Evaluate application data against all configured rules deterministically.

        Ensures:
        1. Sequential, ordered rule evaluation without silent skipping.
        2. Strict aggregation: any mandatory or rule failure prevents approval.
        3. Comprehensive decision traces without leaking sensitive raw values.
        """
        if not isinstance(application_data, dict):
            raise EvaluationError(
                f"Application data must be a dictionary, got {type(application_data).__name__}"
            )

        results: List[RuleEvaluationResult] = []

        for rule in self.config.rules:
            result = self._evaluate_rule(rule, application_data)
            results.append(result)

        total_rules = len(results)
        passed_rules = sum(1 for r in results if r.passed)
        failed_rules = total_rules - passed_rules
        mandatory_failed = any(not r.passed for r in results if r.category == "mandatory")

        # Decision aggregation: all rules must pass for an 'approved' status
        if total_rules == 0:
            status = "approved"
            passed = True
        elif failed_rules > 0:
            status = "rejected"
            passed = False
        else:
            status = "approved"
            passed = True

        return DecisionResult(
            status=status,
            passed=passed,
            total_rules=total_rules,
            passed_rules=passed_rules,
            failed_rules=failed_rules,
            results=results,
            metadata={
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
                "mandatory_failed": mandatory_failed,
                "config_version": self.config.version,
                "config_description": self.config.description,
            },
        )

    def _evaluate_rule(self, rule: Rule, data: Dict[str, Any]) -> RuleEvaluationResult:
        """Route rule to its category-specific evaluation handler."""
        if isinstance(rule, MandatoryRule):
            return self._evaluate_mandatory(rule, data)
        elif isinstance(rule, ThresholdRule):
            return self._evaluate_threshold(rule, data)
        elif isinstance(rule, ConditionalRule):
            return self._evaluate_conditional(rule, data)
        elif isinstance(rule, GroupRule):
            return self._evaluate_group(rule, data)
        else:
            raise EvaluationError(f"Unknown rule type encountered: {type(rule).__name__}")

    def _evaluate_mandatory(self, rule: MandatoryRule, data: Dict[str, Any]) -> RuleEvaluationResult:
        """Evaluate mandatory field presence and non-null/non-empty constraint."""
        val = get_field_value(data, rule.field)

        if val is MISSING:
            passed = False
            reason = f"Mandatory field '{rule.field}' is missing from application data"
        elif val is None:
            passed = False
            reason = f"Mandatory field '{rule.field}' cannot be null"
        elif isinstance(val, str) and not rule.allow_empty_string and val.strip() == "":
            passed = False
            reason = f"Mandatory field '{rule.field}' cannot be an empty string"
        else:
            passed = True
            reason = f"Mandatory field '{rule.field}' is present and non-empty"

        return RuleEvaluationResult(
            rule_id=rule.rule_id,
            category="mandatory",
            passed=passed,
            reason=reason,
            field=rule.field,
            operator="exists",
            expected_value="non-null/non-empty",
            trace={
                "rule_id": rule.rule_id,
                "field": rule.field,
                "operator": "exists",
                "passed": passed,
                "reason": reason,
            },
        )

    def _evaluate_threshold(self, rule: ThresholdRule, data: Dict[str, Any]) -> RuleEvaluationResult:
        """Evaluate numeric value against a configured threshold."""
        val = get_field_value(data, rule.field)
        passed, op_reason = apply_operator(rule.operator, val, rule.threshold)

        if passed:
            reason = f"Field '{rule.field}' satisfies the threshold requirement ({rule.operator} {rule.threshold})"
        else:
            reason = f"Field '{rule.field}' does not satisfy threshold requirement: {op_reason}"

        return RuleEvaluationResult(
            rule_id=rule.rule_id,
            category="threshold",
            passed=passed,
            reason=reason,
            field=rule.field,
            operator=rule.operator,
            expected_value=rule.threshold,
            trace={
                "rule_id": rule.rule_id,
                "field": rule.field,
                "operator": rule.operator,
                "expected_value": rule.threshold,
                "passed": passed,
                "reason": reason,
            },
        )

    def _evaluate_condition_clause(
        self, clause: Union[SimpleCondition, ConditionGroup], data: Dict[str, Any]
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """Recursively evaluate a condition clause or condition group."""
        if isinstance(clause, SimpleCondition):
            val = get_field_value(data, clause.field)
            passed, reason = apply_operator(clause.operator, val, clause.value)
            trace = {
                "field": clause.field,
                "operator": clause.operator,
                "expected_value": clause.value,
                "passed": passed,
                "reason": reason,
            }
            return passed, reason, trace

        elif isinstance(clause, ConditionGroup):
            traces = []
            if clause.combinator == "AND":
                all_passed = True
                failed_reasons = []
                for cond in clause.conditions:
                    c_passed, c_reason, c_trace = self._evaluate_condition_clause(cond, data)
                    traces.append(c_trace)
                    if not c_passed:
                        all_passed = False
                        failed_reasons.append(c_reason)
                summary_reason = (
                    "All AND conditions satisfied"
                    if all_passed
                    else f"AND group failed: {'; '.join(failed_reasons)}"
                )
                return all_passed, summary_reason, {"combinator": "AND", "passed": all_passed, "traces": traces}

            else:  # OR
                any_passed = False
                for cond in clause.conditions:
                    c_passed, c_reason, c_trace = self._evaluate_condition_clause(cond, data)
                    traces.append(c_trace)
                    if c_passed:
                        any_passed = True
                summary_reason = (
                    "At least one OR condition satisfied"
                    if any_passed
                    else "None of the OR conditions were satisfied"
                )
                return any_passed, summary_reason, {"combinator": "OR", "passed": any_passed, "traces": traces}

        else:
            raise EvaluationError(f"Unsupported condition clause type: {type(clause).__name__}")

    def _evaluate_conditional(self, rule: ConditionalRule, data: Dict[str, Any]) -> RuleEvaluationResult:
        """Evaluate an implication rule (when -> then)."""
        when_passed, when_reason, when_trace = self._evaluate_condition_clause(rule.when, data)

        if not when_passed:
            # Condition not triggered; rule passes vacuously
            passed = True
            reason = f"Precondition not met for rule '{rule.rule_id}'; rule passed by default"
            trace = {
                "rule_id": rule.rule_id,
                "precondition_met": False,
                "when_trace": when_trace,
                "then_evaluated": False,
                "passed": True,
            }
        else:
            # Precondition met; evaluate assertion
            then_passed, then_reason, then_trace = self._evaluate_condition_clause(rule.then, data)
            passed = then_passed
            if passed:
                reason = f"Precondition met and assertion satisfied ({then_reason})"
            else:
                reason = f"Precondition met, but assertion failed: {then_reason}"

            trace = {
                "rule_id": rule.rule_id,
                "precondition_met": True,
                "when_trace": when_trace,
                "then_evaluated": True,
                "then_trace": then_trace,
                "passed": passed,
            }

        return RuleEvaluationResult(
            rule_id=rule.rule_id,
            category="conditional",
            passed=passed,
            reason=reason,
            trace=trace,
        )

    def _evaluate_group(self, rule: GroupRule, data: Dict[str, Any]) -> RuleEvaluationResult:
        """Evaluate a composite group rule."""
        clause = ConditionGroup(combinator=rule.combinator, conditions=rule.conditions)
        passed, reason, group_trace = self._evaluate_condition_clause(clause, data)

        return RuleEvaluationResult(
            rule_id=rule.rule_id,
            category="group",
            passed=passed,
            reason=f"Group rule ({rule.combinator}): {reason}",
            trace={
                "rule_id": rule.rule_id,
                "combinator": rule.combinator,
                "passed": passed,
                "details": group_trace,
            },
        )


def evaluate_rules(
    config: Union[RulesConfig, Dict[str, Any], List[Any]],
    application_data: Dict[str, Any],
) -> DecisionResult:
    """Convenience entry point to evaluate rules against application data."""
    evaluator = RulesEvaluator(config)
    return evaluator.evaluate(application_data)

