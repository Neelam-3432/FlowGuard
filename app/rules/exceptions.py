"""Exceptions for the FlowGuard Rules Engine."""


class RulesEngineError(Exception):
    """Base exception for all rules engine errors."""
    pass


class RuleConfigurationError(RulesEngineError):
    """Raised when a rule configuration schema or definition is invalid or malformed."""
    pass


class UnsupportedOperatorError(RulesEngineError):
    """Raised when an unrecognized or disallowed operator is encountered."""
    pass


class InvalidOperandError(RulesEngineError):
    """Raised when operand types are incompatible with the chosen operator."""
    pass


class EvaluationError(RulesEngineError):
    """Raised when an unrecoverable runtime error occurs during rule evaluation."""
    pass

