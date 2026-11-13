"""External verification service simulator for FlowGuard."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class VerificationOutcome(str, Enum):
    """Possible outcomes of external verification."""

    SUCCESS = "SUCCESS"
    TEMPORARY_FAILURE = "TEMPORARY_FAILURE"
    PERSISTENT_FAILURE = "PERSISTENT_FAILURE"


@dataclass(frozen=True)
class VerificationResult:
    """Structured result of an external verification attempt."""

    outcome: VerificationOutcome
    message: str
    details: Dict[str, Any]

    @property
    def is_success(self) -> bool:
        return self.outcome == VerificationOutcome.SUCCESS

    @property
    def is_temporary_failure(self) -> bool:
        return self.outcome == VerificationOutcome.TEMPORARY_FAILURE

    @property
    def is_persistent_failure(self) -> bool:
        return self.outcome == VerificationOutcome.PERSISTENT_FAILURE


class ExternalVerificationSimulator:
    """Deterministic, configurable simulator for external verification dependencies.

    Evaluates simulated conditions based on payload configuration flags without making
    real external network calls.
    """

    def __init__(self, default_outcome: VerificationOutcome = VerificationOutcome.SUCCESS) -> None:
        self.default_outcome = default_outcome

    def verify(
        self,
        input_data: Dict[str, Any],
        retry_count: int = 0,
    ) -> VerificationResult:
        """Simulate an external verification check.

        Outcome selection:
        1. Directive in input_data under 'simulated_verification' or 'verification_simulation'.
        2. Transient recovery:
           - 'TEMPORARY_ONCE': fails when retry_count == 0, recovers on retry_count >= 1.
           - 'fail_until_retry': integer indicating at what retry_count verification recovers.
        3. Defaults to configured default_outcome (SUCCESS).
        """
        directive = (
            input_data.get("simulated_verification")
            or input_data.get("verification_simulation")
        )

        if not directive:
            return VerificationResult(
                outcome=self.default_outcome,
                message="External verification succeeded (default simulation).",
                details={"verified": True, "retry_count": retry_count},
            )

        mode = str(directive).upper().strip()

        if mode == "PERSISTENT_FAILURE":
            return VerificationResult(
                outcome=VerificationOutcome.PERSISTENT_FAILURE,
                message="Persistent verification failure: external identity or fraud check rejected.",
                details={"error_code": "IDENTITY_VERIFICATION_FAILED", "retry_count": retry_count},
            )

        if mode in ("TEMPORARY_FAILURE", "TEMPORARY_ONCE"):
            fail_until_retry = input_data.get("fail_until_retry")
            if mode == "TEMPORARY_ONCE" and fail_until_retry is None:
                fail_until_retry = 1

            if fail_until_retry is not None and retry_count >= int(fail_until_retry):
                return VerificationResult(
                    outcome=VerificationOutcome.SUCCESS,
                    message="External verification succeeded after retry recovery.",
                    details={"recovered": True, "retry_count": retry_count},
                )

            return VerificationResult(
                outcome=VerificationOutcome.TEMPORARY_FAILURE,
                message="Temporary verification failure: external dependency unavailable or timed out.",
                details={"error_code": "DEPENDENCY_TIMEOUT", "retry_count": retry_count},
            )

        if mode == "SUCCESS":
            return VerificationResult(
                outcome=VerificationOutcome.SUCCESS,
                message="External verification succeeded.",
                details={"verified": True, "retry_count": retry_count},
            )

        return VerificationResult(
            outcome=VerificationOutcome.PERSISTENT_FAILURE,
            message=f"Unknown verification directive '{directive}'.",
            details={"error_code": "UNKNOWN_DIRECTIVE", "retry_count": retry_count},
        )


default_verifier = ExternalVerificationSimulator()

