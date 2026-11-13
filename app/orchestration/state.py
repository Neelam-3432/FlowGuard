"""Application state definitions and transition validation."""

from enum import Enum
from typing import Dict, Set
from app.orchestration.exceptions import InvalidStateTransitionError


class ApplicationStatus(str, Enum):
    """Permitted application processing states."""

    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


# Valid directed state transitions mapping
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    ApplicationStatus.PENDING.value: {
        ApplicationStatus.APPROVED.value,
        ApplicationStatus.REJECTED.value,
        ApplicationStatus.FAILED.value,
    },
    ApplicationStatus.APPROVED.value: set(),  # Terminal state
    ApplicationStatus.REJECTED.value: set(),  # Terminal state
    ApplicationStatus.FAILED.value: set(),    # Terminal state
}


def is_valid_transition(current_state: str, new_state: str) -> bool:
    """Check if transitioning from current_state to new_state is allowed."""
    allowed = VALID_TRANSITIONS.get(current_state, set())
    return new_state in allowed


def validate_state_transition(current_state: str, new_state: str) -> None:
    """Validate state transition, raising InvalidStateTransitionError if disallowed."""
    if not is_valid_transition(current_state, new_state):
        raise InvalidStateTransitionError(
            f"Invalid state transition from '{current_state}' to '{new_state}'. "
            f"Allowed next states: {sorted(list(VALID_TRANSITIONS.get(current_state, set())))}"
        )


def is_terminal_state(state: str) -> bool:
    """Check whether a given state is terminal (no further transitions allowed)."""
    return len(VALID_TRANSITIONS.get(state, set())) == 0

