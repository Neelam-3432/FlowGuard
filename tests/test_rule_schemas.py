"""Tests for rule configuration schemas and validation."""

import pytest
from app.rules.exceptions import RuleConfigurationError
from app.rules.schemas import (
    ConditionalRule,
    ConditionGroup,
    GroupRule,
    MandatoryRule,
    RulesConfig,
    SimpleCondition,
    ThresholdRule,
    load_rules_config,
)


def test_valid_mandatory_rule_schema() -> None:
    """Verify that valid mandatory field rules parse correctly."""
    config_data = {
        "rules": [
            {
                "rule_id": "REQ_NAME",
                "category": "mandatory",
                "field": "applicant_name",
                "description": "Applicant name is mandatory",
                "allow_empty_string": False,
            }
        ]
    }
    config = load_rules_config(config_data)
    assert len(config.rules) == 1
    rule = config.rules[0]
    assert isinstance(rule, MandatoryRule)
    assert rule.rule_id == "REQ_NAME"
    assert rule.field == "applicant_name"
    assert rule.allow_empty_string is False


def test_valid_threshold_rule_schema() -> None:
    """Verify that valid threshold rules with int and float thresholds parse correctly."""
    config_data = {
        "rules": [
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
                "operator": "gt",
                "threshold": 300000.50,
            },
        ]
    }
    config = load_rules_config(config_data)
    assert len(config.rules) == 2
    assert isinstance(config.rules[0], ThresholdRule)
    assert config.rules[0].threshold == 18
    assert isinstance(config.rules[1], ThresholdRule)
    assert config.rules[1].threshold == 300000.50


def test_valid_conditional_rule_schema() -> None:
    """Verify that conditional implication rules parse correctly."""
    config_data = {
        "rules": [
            {
                "rule_id": "SALARIED_SALARY_CHECK",
                "category": "conditional",
                "when": {
                    "field": "employment_type",
                    "operator": "eq",
                    "value": "salaried",
                },
                "then": {
                    "field": "monthly_salary",
                    "operator": "gt",
                    "value": 0,
                },
            }
        ]
    }
    config = load_rules_config(config_data)
    assert len(config.rules) == 1
    rule = config.rules[0]
    assert isinstance(rule, ConditionalRule)
    assert isinstance(rule.when, SimpleCondition)
    assert rule.when.field == "employment_type"
    assert isinstance(rule.then, SimpleCondition)
    assert rule.then.operator == "gt"


def test_valid_group_rule_schema() -> None:
    """Verify that composite group rules with AND / OR combinators parse correctly."""
    config_data = {
        "rules": [
            {
                "rule_id": "RESIDENCE_CHECK",
                "category": "group",
                "combinator": "OR",
                "conditions": [
                    {"field": "country", "operator": "eq", "value": "US"},
                    {"field": "country", "operator": "eq", "value": "CA"},
                ],
            }
        ]
    }
    config = load_rules_config(config_data)
    assert len(config.rules) == 1
    rule = config.rules[0]
    assert isinstance(rule, GroupRule)
    assert rule.combinator == "OR"
    assert len(rule.conditions) == 2


def test_invalid_operator_rejected() -> None:
    """Verify that unapproved operators raise RuleConfigurationError."""
    config_data = {
        "rules": [
            {
                "rule_id": "REGEX_RULE",
                "category": "conditional",
                "when": {"field": "email", "operator": "matches_regex", "value": ".*@.*"},
                "then": {"field": "status", "operator": "eq", "value": "VALID"},
            }
        ]
    }
    with pytest.raises(RuleConfigurationError, match="not in the approved whitelist"):
        load_rules_config(config_data)


def test_missing_required_property_rejected() -> None:
    """Verify that rules missing required properties (such as rule_id or field) fail validation."""
    # Missing rule_id
    with pytest.raises(RuleConfigurationError):
        load_rules_config({
            "rules": [
                {
                    "category": "mandatory",
                    "field": "applicant_name",
                }
            ]
        })

    # Missing field in threshold rule
    with pytest.raises(RuleConfigurationError):
        load_rules_config({
            "rules": [
                {
                    "rule_id": "TEST_RULE",
                    "category": "threshold",
                    "operator": "gt",
                    "threshold": 100,
                }
            ]
        })


def test_invalid_threshold_type_rejected() -> None:
    """Verify that non-numeric or boolean threshold values are rejected."""
    # Boolean threshold (cannot be treated as numeric in rules engine)
    with pytest.raises(RuleConfigurationError, match="Threshold must be numeric"):
        load_rules_config({
            "rules": [
                {
                    "rule_id": "BOOL_THRESHOLD",
                    "category": "threshold",
                    "field": "score",
                    "operator": "gte",
                    "threshold": True,
                }
            ]
        })

    # String threshold
    with pytest.raises(RuleConfigurationError, match="Threshold must be numeric"):
        load_rules_config({
            "rules": [
                {
                    "rule_id": "STR_THRESHOLD",
                    "category": "threshold",
                    "field": "score",
                    "operator": "gte",
                    "threshold": "one hundred",
                }
            ]
        })


def test_malformed_rule_group_excessive_depth() -> None:
    """Verify that nested condition groups exceeding max depth limit of 3 are rejected."""
    deeply_nested = {
        "rule_id": "DEEP_GROUP",
        "category": "group",
        "combinator": "AND",
        "conditions": [
            {
                "combinator": "AND",
                "conditions": [
                    {
                        "combinator": "AND",
                        "conditions": [
                            {
                                "combinator": "AND",
                                "conditions": [
                                    {"field": "a", "operator": "eq", "value": 1}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    with pytest.raises(RuleConfigurationError, match="maximum nesting depth limit of 3"):
        load_rules_config({"rules": [deeply_nested]})


def test_unknown_rule_category_rejected() -> None:
    """Verify that unknown rule categories raise RuleConfigurationError."""
    with pytest.raises(RuleConfigurationError):
        load_rules_config({
            "rules": [
                {
                    "rule_id": "UNKNOWN_RULE",
                    "category": "custom_script",
                    "field": "data",
                }
            ]
        })


def test_load_rules_config_from_various_inputs() -> None:
    """Verify load_rules_config supports dict, list, and RulesConfig instances."""
    raw_list = [
        {"rule_id": "R1", "category": "mandatory", "field": "name"}
    ]
    # From list
    cfg1 = load_rules_config(raw_list)
    assert len(cfg1.rules) == 1

    # From dict
    cfg2 = load_rules_config({"rules": raw_list, "version": "1.0"})
    assert cfg2.version == "1.0"

    # From RulesConfig instance
    cfg3 = load_rules_config(cfg2)
    assert cfg3 is cfg2

    # Invalid input type
    with pytest.raises(RuleConfigurationError):
        load_rules_config("invalid string input")  # type: ignore[arg-type]

