"""Tests for deterministic rules evaluation engine."""

import pytest
from app.rules.evaluator import RulesEvaluator, evaluate_rules
from app.rules.exceptions import EvaluationError


@pytest.fixture
def standard_rules_config() -> dict:
    """Fixture providing a standard multi-category rule configuration."""
    return {
        "version": "1.0",
        "description": "Standard Loan Approval Workflow Rules",
        "rules": [
            {
                "rule_id": "REQ_APPLICANT_NAME",
                "category": "mandatory",
                "field": "applicant_name",
            },
            {
                "rule_id": "MIN_AGE",
                "category": "threshold",
                "field": "applicant_age",
                "operator": "gte",
                "threshold": 18,
            },
            {
                "rule_id": "MIN_INCOME",
                "category": "threshold",
                "field": "annual_income",
                "operator": "gte",
                "threshold": 300000,
            },
            {
                "rule_id": "SALARIED_PROOF",
                "category": "conditional",
                "when": {"field": "employment_type", "operator": "eq", "value": "salaried"},
                "then": {"field": "monthly_salary", "operator": "gt", "value": 0},
            },
        ],
    }


def test_evaluator_all_rules_passing(standard_rules_config: dict) -> None:
    """Verify that when all rules are satisfied, status is 'approved' and passed is True."""
    app_data = {
        "applicant_name": "Bob Smith",
        "applicant_age": 28,
        "annual_income": 500000,
        "employment_type": "salaried",
        "monthly_salary": 40000,
    }

    decision = evaluate_rules(standard_rules_config, app_data)

    assert decision.status == "approved"
    assert decision.passed is True
    assert decision.total_rules == 4
    assert decision.passed_rules == 4
    assert decision.failed_rules == 0
    assert len(decision.results) == 4
    for result in decision.results:
        assert result.passed is True


def test_evaluator_one_threshold_rule_failing(standard_rules_config: dict) -> None:
    """Verify that a single threshold rule failure results in status 'rejected'."""
    app_data = {
        "applicant_name": "Charlie",
        "applicant_age": 16,  # Below threshold 18
        "annual_income": 400000,
        "employment_type": "self_employed",
    }

    decision = evaluate_rules(standard_rules_config, app_data)

    assert decision.status == "rejected"
    assert decision.passed is False
    assert decision.total_rules == 4
    assert decision.passed_rules == 3
    assert decision.failed_rules == 1

    # Specifically check the failing rule result
    age_result = next(r for r in decision.results if r.rule_id == "MIN_AGE")
    assert age_result.passed is False
    assert "does not satisfy threshold" in age_result.reason


def test_evaluator_multiple_rules_failing(standard_rules_config: dict) -> None:
    """Verify that multiple rule failures are all collected and reported."""
    app_data = {
        "applicant_name": "Diana",
        "applicant_age": 16,  # Fails threshold
        "annual_income": 150000,  # Fails threshold
        "employment_type": "salaried",
        "monthly_salary": 0,  # Fails conditional rule
    }

    decision = evaluate_rules(standard_rules_config, app_data)

    assert decision.status == "rejected"
    assert decision.passed is False
    assert decision.failed_rules == 3
    assert decision.passed_rules == 1  # Only REQ_APPLICANT_NAME passed


def test_evaluator_mandatory_rule_failure(standard_rules_config: dict) -> None:
    """Verify that a missing or null mandatory field causes overall rejection."""
    # Missing applicant_name
    app_data = {
        "applicant_age": 30,
        "annual_income": 600000,
    }

    decision = evaluate_rules(standard_rules_config, app_data)

    assert decision.status == "rejected"
    assert decision.passed is False
    assert decision.metadata["mandatory_failed"] is True

    name_result = next(r for r in decision.results if r.rule_id == "REQ_APPLICANT_NAME")
    assert name_result.passed is False
    assert "missing" in name_result.reason


def test_evaluator_mandatory_empty_string() -> None:
    """Verify mandatory field whitespace/empty string handling."""
    config = {
        "rules": [
            {
                "rule_id": "STRICT_NAME",
                "category": "mandatory",
                "field": "name",
                "allow_empty_string": False,
            },
            {
                "rule_id": "OPTIONAL_DESC",
                "category": "mandatory",
                "field": "notes",
                "allow_empty_string": True,
            },
        ]
    }
    app_data = {"name": "   ", "notes": ""}

    decision = evaluate_rules(config, app_data)

    assert decision.status == "rejected"
    name_res = next(r for r in decision.results if r.rule_id == "STRICT_NAME")
    assert name_res.passed is False

    notes_res = next(r for r in decision.results if r.rule_id == "OPTIONAL_DESC")
    assert notes_res.passed is True


def test_evaluator_conditional_rule_scenarios() -> None:
    """Verify conditional rule behavior when precondition is met vs not met."""
    config = {
        "rules": [
            {
                "rule_id": "COND_SELF_EMPLOYED",
                "category": "conditional",
                "when": {"field": "employment_type", "operator": "eq", "value": "self_employed"},
                "then": {"field": "business_income", "operator": "gt", "value": 100000},
            }
        ]
    }

    # Scenario 1: Precondition met, assertion passed -> Passes
    d1 = evaluate_rules(config, {"employment_type": "self_employed", "business_income": 200000})
    assert d1.status == "approved"
    assert d1.results[0].passed is True

    # Scenario 2: Precondition met, assertion failed -> Fails
    d2 = evaluate_rules(config, {"employment_type": "self_employed", "business_income": 50000})
    assert d2.status == "rejected"
    assert d2.results[0].passed is False

    # Scenario 3: Precondition not met -> Passes by default
    d3 = evaluate_rules(config, {"employment_type": "student"})
    assert d3.status == "approved"
    assert d3.results[0].passed is True
    assert "Precondition not met" in d3.results[0].reason


def test_evaluator_group_rule_and_or_combinators() -> None:
    """Verify GroupRule evaluation with AND and OR combinators."""
    config = {
        "rules": [
            {
                "rule_id": "AND_GROUP",
                "category": "group",
                "combinator": "AND",
                "conditions": [
                    {"field": "score", "operator": "gte", "value": 700},
                    {"field": "has_id", "operator": "eq", "value": True},
                ],
            },
            {
                "rule_id": "OR_GROUP",
                "category": "group",
                "combinator": "OR",
                "conditions": [
                    {"field": "tier", "operator": "eq", "value": "VIP"},
                    {"field": "referral", "operator": "eq", "value": True},
                ],
            },
        ]
    }

    # Case 1: Both groups satisfy conditions
    d1 = evaluate_rules(config, {"score": 750, "has_id": True, "tier": "STANDARD", "referral": True})
    assert d1.status == "approved"

    # Case 2: AND group fails
    d2 = evaluate_rules(config, {"score": 650, "has_id": True, "tier": "VIP"})
    assert d2.status == "rejected"
    and_res = next(r for r in d2.results if r.rule_id == "AND_GROUP")
    assert and_res.passed is False

    # Case 3: OR group fails (neither condition met)
    d3 = evaluate_rules(config, {"score": 720, "has_id": True, "tier": "BASIC", "referral": False})
    assert d3.status == "rejected"
    or_res = next(r for r in d3.results if r.rule_id == "OR_GROUP")
    assert or_res.passed is False


def test_evaluator_empty_configuration() -> None:
    """Verify that an empty rule configuration yields status 'approved' with 0 rules."""
    decision = evaluate_rules({"rules": []}, {"any_key": "any_value"})
    assert decision.status == "approved"
    assert decision.passed is True
    assert decision.total_rules == 0
    assert decision.passed_rules == 0
    assert decision.failed_rules == 0
    assert decision.results == []


def test_evaluator_missing_and_incorrect_types() -> None:
    """Verify that missing fields and invalid types in application data fail safely without crashing."""
    config = {
        "rules": [
            {
                "rule_id": "NUMERIC_RULE",
                "category": "threshold",
                "field": "score",
                "operator": "gte",
                "threshold": 700,
            }
        ]
    }

    # Missing field
    d_missing = evaluate_rules(config, {})
    assert d_missing.status == "rejected"
    assert "missing" in d_missing.results[0].reason

    # Incorrect type (string instead of int)
    d_wrong_type = evaluate_rules(config, {"score": "not_a_number"})
    assert d_wrong_type.status == "rejected"
    assert "not numeric" in d_wrong_type.results[0].reason


def test_evaluator_invalid_application_data_non_dict() -> None:
    """Verify that passing non-dictionary application data raises EvaluationError."""
    evaluator = RulesEvaluator({"rules": []})
    with pytest.raises(EvaluationError, match="must be a dictionary"):
        evaluator.evaluate(["invalid", "list"])  # type: ignore[arg-type]


def test_evaluator_deterministic_ordering() -> None:
    """Verify that rules are evaluated in the exact order configured."""
    rule_ids = [f"RULE_{i}" for i in range(10)]
    config = {
        "rules": [
            {"rule_id": rid, "category": "mandatory", "field": f"field_{i}"}
            for i, rid in enumerate(rule_ids)
        ]
    }
    app_data = {f"field_{i}": f"value_{i}" for i in range(10)}

    decision = evaluate_rules(config, app_data)

    evaluated_ids = [r.rule_id for r in decision.results]
    assert evaluated_ids == rule_ids


def test_evaluator_nested_dot_notation() -> None:
    """Verify evaluation of nested application fields using dot notation."""
    config = {
        "rules": [
            {
                "rule_id": "NESTED_SALARY",
                "category": "threshold",
                "field": "financials.salary.amount",
                "operator": "gte",
                "threshold": 50000,
            }
        ]
    }
    app_data = {
        "financials": {
            "salary": {
                "amount": 75000
            }
        }
    }

    decision = evaluate_rules(config, app_data)
    assert decision.status == "approved"
    assert decision.results[0].passed is True

