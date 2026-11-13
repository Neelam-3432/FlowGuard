"""Safe operator registry and evaluation functions for FlowGuard Rules Engine."""

from typing import Any, Callable, Dict, Set, Tuple
from app.rules.exceptions import InvalidOperandError, UnsupportedOperatorError


class _MissingSentinel:
    """Sentinel object representing a missing field in application data."""

    def __repr__(self) -> str:
        return "<MISSING>"

    def __str__(self) -> str:
        return "<MISSING>"


MISSING = _MissingSentinel()


def op_exists(actual: Any, expected: Any = None) -> Tuple[bool, str]:
    """Check that field exists, is not null, and is not an empty string."""
    if actual is MISSING:
        return False, "Field is missing from application data"
    if actual is None:
        return False, "Field value is null"
    if isinstance(actual, str) and actual.strip() == "":
        return False, "Field value is an empty string"
    return True, "Field exists and has a non-empty value"


def op_not_exists(actual: Any, expected: Any = None) -> Tuple[bool, str]:
    """Check that field does not exist, is null, or is an empty string."""
    if actual is MISSING:
        return True, "Field is missing from application data"
    if actual is None:
        return True, "Field value is null"
    if isinstance(actual, str) and actual.strip() == "":
        return True, "Field value is an empty string"
    return False, "Field exists and contains a value"


def op_eq(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check strict equality between actual and expected values."""
    if actual is MISSING:
        return False, "Field is missing from application data"

    # Guard against Python's implicit True == 1 coercion
    if isinstance(actual, bool) != isinstance(expected, bool):
        return (
            False,
            f"Type mismatch: cannot compare boolean with non-boolean (expected {type(expected).__name__}, got {type(actual).__name__})",
        )

    if actual == expected:
        return True, f"Value equals expected value ({expected})"
    return False, f"Value does not equal expected value ({expected})"


def op_ne(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check strict inequality between actual and expected values."""
    if actual is MISSING:
        return False, "Field is missing from application data"

    if isinstance(actual, bool) != isinstance(expected, bool):
        return True, f"Value type differs from expected value ({expected})"

    if actual != expected:
        return True, f"Value does not equal ({expected})"
    return False, f"Value unexpectedly equals ({expected})"


def _validate_numeric(name: str, value: Any, raise_on_error: bool = False) -> bool:
    """Verify that a value is a valid numeric type (int or float, not bool)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        if raise_on_error:
            raise InvalidOperandError(
                f"{name} must be numeric (int or float), got {type(value).__name__}"
            )
        return False
    return True


def op_gt(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check that actual numeric value is strictly greater than expected."""
    _validate_numeric("Expected threshold", expected, raise_on_error=True)

    if actual is MISSING:
        return False, "Field is missing from application data"
    if actual is None:
        return False, "Field value is null"
    if not _validate_numeric("Actual value", actual):
        return False, f"Actual value is not numeric (got {type(actual).__name__})"

    if actual > expected:
        return True, f"Value satisfies condition (> {expected})"
    return False, f"Value does not satisfy condition (must be > {expected})"


def op_gte(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check that actual numeric value is greater than or equal to expected."""
    _validate_numeric("Expected threshold", expected, raise_on_error=True)

    if actual is MISSING:
        return False, "Field is missing from application data"
    if actual is None:
        return False, "Field value is null"
    if not _validate_numeric("Actual value", actual):
        return False, f"Actual value is not numeric (got {type(actual).__name__})"

    if actual >= expected:
        return True, f"Value satisfies condition (>= {expected})"
    return False, f"Value does not satisfy condition (must be >= {expected})"


def op_lt(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check that actual numeric value is strictly less than expected."""
    _validate_numeric("Expected threshold", expected, raise_on_error=True)

    if actual is MISSING:
        return False, "Field is missing from application data"
    if actual is None:
        return False, "Field value is null"
    if not _validate_numeric("Actual value", actual):
        return False, f"Actual value is not numeric (got {type(actual).__name__})"

    if actual < expected:
        return True, f"Value satisfies condition (< {expected})"
    return False, f"Value does not satisfy condition (must be < {expected})"


def op_lte(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check that actual numeric value is less than or equal to expected."""
    _validate_numeric("Expected threshold", expected, raise_on_error=True)

    if actual is MISSING:
        return False, "Field is missing from application data"
    if actual is None:
        return False, "Field value is null"
    if not _validate_numeric("Actual value", actual):
        return False, f"Actual value is not numeric (got {type(actual).__name__})"

    if actual <= expected:
        return True, f"Value satisfies condition (<= {expected})"
    return False, f"Value does not satisfy condition (must be <= {expected})"


def op_in(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check that actual value is contained within the expected collection."""
    if not isinstance(expected, (list, tuple, set)):
        raise InvalidOperandError(
            f"Operator 'in' requires collection operand (list, tuple, set), got {type(expected).__name__}"
        )

    if actual is MISSING:
        return False, "Field is missing from application data"

    if actual in expected:
        return True, "Value is in allowed collection"
    return False, "Value is not in allowed collection"


def op_not_in(actual: Any, expected: Any) -> Tuple[bool, str]:
    """Check that actual value is not contained within the expected collection."""
    if not isinstance(expected, (list, tuple, set)):
        raise InvalidOperandError(
            f"Operator 'not_in' requires collection operand (list, tuple, set), got {type(expected).__name__}"
        )

    if actual is MISSING:
        return False, "Field is missing from application data"

    if actual not in expected:
        return True, "Value is not in disallowed collection"
    return False, "Value is present in disallowed collection"


# Predefined, immutable operator dispatch registry
OPERATOR_REGISTRY: Dict[str, Callable[[Any, Any], Tuple[bool, str]]] = {
    "eq": op_eq,
    "ne": op_ne,
    "gt": op_gt,
    "gte": op_gte,
    "lt": op_lt,
    "lte": op_lte,
    "in": op_in,
    "not_in": op_not_in,
    "exists": op_exists,
    "not_exists": op_not_exists,
}

ALLOWED_OPERATORS: Set[str] = set(OPERATOR_REGISTRY.keys())


def is_valid_operator(operator: str) -> bool:
    """Check whether an operator is in the approved whitelist."""
    return operator in ALLOWED_OPERATORS


def apply_operator(operator: str, actual: Any, expected: Any = None) -> Tuple[bool, str]:
    """Safely apply a registered operator to operands without dynamic evaluation."""
    if operator not in OPERATOR_REGISTRY:
        raise UnsupportedOperatorError(
            f"Operator '{operator}' is not supported. Allowed operators: {sorted(list(ALLOWED_OPERATORS))}"
        )

    handler = OPERATOR_REGISTRY[operator]
    return handler(actual, expected)

