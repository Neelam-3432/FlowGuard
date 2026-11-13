"""Tests for safe operator registry and evaluation functions."""

import pytest
from app.rules.exceptions import InvalidOperandError, UnsupportedOperatorError
from app.rules.operators import (
    ALLOWED_OPERATORS,
    MISSING,
    apply_operator,
    is_valid_operator,
)


def test_is_valid_operator_whitelist() -> None:
    """Verify that only the exact 10 whitelisted operators are accepted."""
    expected_whitelist = {"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in", "exists", "not_exists"}
    assert ALLOWED_OPERATORS == expected_whitelist

    for op in expected_whitelist:
        assert is_valid_operator(op) is True

    # Disallowed operators
    for bad_op in ["eval", "exec", "regex", "like", "contains", "custom", ""]:
        assert is_valid_operator(bad_op) is False


def test_op_exists_and_not_exists() -> None:
    """Verify 'exists' and 'not_exists' operators across various value representations."""
    # Exists checks
    assert apply_operator("exists", "Alice")[0] is True
    assert apply_operator("exists", 0)[0] is True
    assert apply_operator("exists", False)[0] is True
    assert apply_operator("exists", "")[0] is False  # Empty string rejected
    assert apply_operator("exists", "   ")[0] is False  # Whitespace rejected
    assert apply_operator("exists", None)[0] is False  # None rejected
    assert apply_operator("exists", MISSING)[0] is False  # Missing rejected

    # Not-exists checks
    assert apply_operator("not_exists", MISSING)[0] is True
    assert apply_operator("not_exists", None)[0] is True
    assert apply_operator("not_exists", "")[0] is True
    assert apply_operator("not_exists", "Alice")[0] is False
    assert apply_operator("not_exists", 100)[0] is False


def test_op_eq_strict_types() -> None:
    """Verify 'eq' handles equality strictly without implicit boolean-to-integer coercion."""
    # Standard equality
    assert apply_operator("eq", 42, 42)[0] is True
    assert apply_operator("eq", "approved", "approved")[0] is True
    assert apply_operator("eq", "approved", "rejected")[0] is False

    # Guard: Python True == 1 coercion must be prevented
    passed, reason = apply_operator("eq", True, 1)
    assert passed is False
    assert "Type mismatch" in reason

    passed, reason = apply_operator("eq", False, 0)
    assert passed is False
    assert "Type mismatch" in reason

    # Missing field
    assert apply_operator("eq", MISSING, "expected")[0] is False


def test_op_ne_strict_types() -> None:
    """Verify 'ne' handles inequality strictly."""
    assert apply_operator("ne", "pending", "approved")[0] is True
    assert apply_operator("ne", 10, 20)[0] is True
    assert apply_operator("ne", "same", "same")[0] is False
    assert apply_operator("ne", True, 1)[0] is True  # Distinct types differ
    assert apply_operator("ne", MISSING, "value")[0] is False


def test_op_gt_and_gte_numeric() -> None:
    """Verify 'gt' and 'gte' comparison operators and boundary values."""
    # gt
    assert apply_operator("gt", 25, 18)[0] is True
    assert apply_operator("gt", 18, 18)[0] is False
    assert apply_operator("gt", 17, 18)[0] is False

    # gte
    assert apply_operator("gte", 18, 18)[0] is True
    assert apply_operator("gte", 18.0, 18)[0] is True
    assert apply_operator("gte", 17.9, 18)[0] is False

    # Non-numeric actual values fail safely without exceptions
    assert apply_operator("gt", "twenty", 18)[0] is False
    assert apply_operator("gt", None, 18)[0] is False
    assert apply_operator("gt", MISSING, 18)[0] is False
    assert apply_operator("gt", True, 0)[0] is False  # Bool is rejected as numeric

    # Non-numeric expected threshold raises InvalidOperandError
    with pytest.raises(InvalidOperandError):
        apply_operator("gt", 25, "eighteen")


def test_op_lt_and_lte_numeric() -> None:
    """Verify 'lt' and 'lte' comparison operators and boundary values."""
    # lt
    assert apply_operator("lt", 15, 18)[0] is True
    assert apply_operator("lt", 18, 18)[0] is False
    assert apply_operator("lt", 19, 18)[0] is False

    # lte
    assert apply_operator("lte", 18, 18)[0] is True
    assert apply_operator("lte", 18.0, 18)[0] is True
    assert apply_operator("lte", 18.1, 18)[0] is False

    # Missing or null fails safely
    assert apply_operator("lt", None, 18)[0] is False
    assert apply_operator("lt", MISSING, 18)[0] is False

    with pytest.raises(InvalidOperandError):
        apply_operator("lte", 10, True)


def test_op_in_and_not_in() -> None:
    """Verify 'in' and 'not_in' collection membership operators."""
    allowed_tiers = ["silver", "gold", "platinum"]

    # in
    assert apply_operator("in", "gold", allowed_tiers)[0] is True
    assert apply_operator("in", "bronze", allowed_tiers)[0] is False
    assert apply_operator("in", MISSING, allowed_tiers)[0] is False

    # not_in
    assert apply_operator("not_in", "bronze", allowed_tiers)[0] is True
    assert apply_operator("not_in", "gold", allowed_tiers)[0] is False
    assert apply_operator("not_in", MISSING, allowed_tiers)[0] is False

    # Non-collection operand raises InvalidOperandError
    with pytest.raises(InvalidOperandError):
        apply_operator("in", "gold", 12345)

    with pytest.raises(InvalidOperandError):
        apply_operator("not_in", "gold", "plain_string")


def test_unsupported_operator_dispatch() -> None:
    """Verify that executing an unsupported operator raises UnsupportedOperatorError."""
    with pytest.raises(UnsupportedOperatorError, match="not supported"):
        apply_operator("dynamic_eval", 10, 10)

