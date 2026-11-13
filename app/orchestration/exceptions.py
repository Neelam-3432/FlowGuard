"""Exceptions for the FlowGuard Workflow Orchestration Layer."""


class OrchestrationError(Exception):
    """Base exception for all workflow orchestration errors."""
    pass


class WorkflowNotFoundError(OrchestrationError):
    """Raised when the requested workflow configuration is not found."""
    pass


class InvalidWorkflowConfigError(OrchestrationError):
    """Raised when a persisted workflow configuration fails schema validation."""
    pass


class IdempotencyConflictError(OrchestrationError):
    """Raised when an idempotency key is reused with a different payload."""
    pass


class InvalidStateTransitionError(OrchestrationError):
    """Raised when an illegal or disallowed application state transition is attempted."""
    pass

