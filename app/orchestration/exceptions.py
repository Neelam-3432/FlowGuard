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


class ApplicationNotFoundError(OrchestrationError):
    """Raised when an application is not found by ID."""
    pass


class IneligibleRetryError(OrchestrationError):
    """Raised when attempting to retry an application that is not in RETRY_PENDING status."""
    pass


class RetryLimitExceededError(OrchestrationError):
    """Raised when retry attempts exceed the configured maximum threshold."""
    pass
