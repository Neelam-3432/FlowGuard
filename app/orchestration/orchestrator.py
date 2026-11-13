"""Workflow Orchestrator managing application execution lifecycle, retries, and resilience."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.workflow_config import WorkflowConfig
from app.orchestration.exceptions import (
    ApplicationNotFoundError,
    IdempotencyConflictError,
    IneligibleRetryError,
    InvalidStateTransitionError,
    InvalidWorkflowConfigError,
    RetryLimitExceededError,
    WorkflowNotFoundError,
)
from app.orchestration.state import (
    ApplicationStatus,
    is_eligible_for_retry,
    validate_state_transition,
)
from app.rules.decision import DecisionResult
from app.rules.evaluator import evaluate_rules
from app.rules.exceptions import RuleConfigurationError
from app.rules.schemas import load_rules_config
from app.schemas.application import (
    ApplicationCreateRequest,
    ApplicationResponse,
    DecisionSummaryResponse,
    RuleSummaryResponse,
)
from app.services.workflow_config_service import (
    get_active_workflow_config,
    get_workflow_config_by_version,
)
from app.verification.simulator import (
    ExternalVerificationSimulator,
    VerificationResult,
    default_verifier,
)


def compute_payload_hash(data: Dict[str, Any]) -> str:
    """Compute deterministic SHA-256 hash of application input data."""
    serialized = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_decision_summary_from_decision(decision: DecisionResult) -> DecisionSummaryResponse:
    """Convert Rules Engine DecisionResult into API DecisionSummaryResponse without exposing sensitive values."""
    rule_summaries = [
        RuleSummaryResponse(
            rule_id=res.rule_id,
            category=res.category,
            passed=res.passed,
            reason=res.reason,
        )
        for res in decision.results
    ]
    return DecisionSummaryResponse(
        status=decision.status,
        passed=decision.passed,
        total_rules=decision.total_rules,
        passed_rules=decision.passed_rules,
        failed_rules=decision.failed_rules,
        results=rule_summaries,
        metadata=decision.metadata,
    )


def _reconstruct_decision_summary_from_audit(
    audit_log: Optional[AuditLog], current_status: Optional[str] = None
) -> Optional[DecisionSummaryResponse]:
    """Reconstruct a decision summary from stored audit log details for idempotent replays."""
    if not audit_log or not audit_log.details:
        return None

    details = audit_log.details
    return DecisionSummaryResponse(
        status=current_status or details.get("status", "unknown"),
        passed=details.get("passed", False),
        total_rules=details.get("total_rules", 0),
        passed_rules=details.get("passed_rules", 0),
        failed_rules=details.get("failed_rules", 0),
        results=[],
        metadata={"replayed": True, "workflow_version": details.get("workflow_version")},
    )


@dataclass
class ProcessedApplicationResult:
    """Container holding application entity, decision summary, and execution details."""

    application: Application
    decision_summary: Optional[DecisionSummaryResponse]
    is_idempotent_replay: bool = False
    verification_outcome: Optional[str] = None
    failure_reason: Optional[str] = None

    def to_response(self) -> ApplicationResponse:
        """Convert result into standard API ApplicationResponse schema."""
        version = (
            self.application.workflow_config.version
            if self.application.workflow_config
            else 0
        )
        return ApplicationResponse(
            id=self.application.id,
            request_id=self.application.request_id,
            workflow_id=self.application.workflow_id,
            workflow_config_id=self.application.workflow_config_id,
            workflow_version=version,
            idempotency_key=self.application.idempotency_key,
            status=self.application.status,
            retry_count=self.application.retry_count,
            verification_outcome=self.verification_outcome,
            failure_reason=self.failure_reason,
            decision=self.decision_summary,
            created_at=self.application.created_at,
            updated_at=self.application.updated_at,
        )


class WorkflowOrchestrator:
    """Orchestrates application evaluation, external verification, retries, and persistence."""

    def __init__(self, verifier: Optional[ExternalVerificationSimulator] = None) -> None:
        self.verifier = verifier or default_verifier

    def process_application(
        self, db: Session, submission: ApplicationCreateRequest
    ) -> ProcessedApplicationResult:
        """Process an application submission through the workflow lifecycle."""
        payload_hash = compute_payload_hash(submission.input_data)

        # 1. Check for existing submission (Application-level idempotency check)
        existing = (
            db.query(Application)
            .filter(
                Application.workflow_id == submission.workflow_id,
                Application.idempotency_key == submission.idempotency_key,
            )
            .first()
        )

        if existing:
            if existing.payload_hash == payload_hash:
                # Idempotent replay: return existing record without duplicating audit logs
                latest_audit = (
                    db.query(AuditLog)
                    .filter(AuditLog.application_id == existing.id)
                    .order_by(AuditLog.id.desc())
                    .first()
                )
                rules_audit = (
                    db.query(AuditLog)
                    .filter(AuditLog.application_id == existing.id)
                    .order_by(AuditLog.id.asc())
                    .first()
                )
                summary = _reconstruct_decision_summary_from_audit(rules_audit, current_status=existing.status)
                audit_ver = (
                    latest_audit.details.get("verification", {}).get("outcome")
                    if (
                        latest_audit
                        and latest_audit.details
                        and isinstance(latest_audit.details.get("verification"), dict)
                    )
                    else None
                )
                audit_failure = (
                    latest_audit.details.get("verification", {}).get("message")
                    if (
                        latest_audit
                        and latest_audit.details
                        and isinstance(latest_audit.details.get("verification"), dict)
                    )
                    else None
                )
                return ProcessedApplicationResult(
                    application=existing,
                    decision_summary=summary,
                    is_idempotent_replay=True,
                    verification_outcome=audit_ver,
                    failure_reason=audit_failure,
                )
            else:
                # Same idempotency key used with different submission payload
                raise IdempotencyConflictError(
                    f"Idempotency key '{submission.idempotency_key}' was already used "
                    f"for workflow '{submission.workflow_id}' with different submission data."
                )

        # 2. Retrieve appropriate workflow configuration
        if submission.workflow_version is not None:
            config = get_workflow_config_by_version(
                db, submission.workflow_id, submission.workflow_version
            )
        else:
            config = get_active_workflow_config(db, submission.workflow_id)

        if not config:
            version_str = f" v{submission.workflow_version}" if submission.workflow_version else ""
            raise WorkflowNotFoundError(
                f"Workflow '{submission.workflow_id}'{version_str} configuration not found or inactive."
            )

        # 3. Validate workflow configuration schema
        try:
            rules_config = load_rules_config(config.config_data)
        except RuleConfigurationError as e:
            raise InvalidWorkflowConfigError(
                f"Workflow '{submission.workflow_id}' configuration (ID: {config.id}) is invalid: {e}"
            ) from e

        # 4. Evaluate rules with the Rules Engine
        decision = evaluate_rules(rules_config, submission.input_data)

        max_retries = (
            config.config_data.get("max_retries", settings.max_retries)
            if isinstance(config.config_data, dict)
            else settings.max_retries
        )

        verification_outcome: Optional[str] = None
        failure_reason: Optional[str] = None

        # 5. Evaluate business decision & external verification OUTSIDE of DB transaction
        if not decision.passed:
            # Business rules failed: permanent rejection (never retried)
            target_status = ApplicationStatus.REJECTED.value
            event_type = "APPLICATION_REJECTED"
            failure_reason = "Rules evaluation failed"
        else:
            # Rules passed: invoke external verification simulator outside DB transaction
            ver_res: VerificationResult = self.verifier.verify(submission.input_data, retry_count=0)
            verification_outcome = ver_res.outcome.value

            if ver_res.is_success:
                target_status = ApplicationStatus.APPROVED.value
                event_type = "APPLICATION_APPROVED"
            elif ver_res.is_temporary_failure:
                if max_retries > 0:
                    target_status = ApplicationStatus.RETRY_PENDING.value
                    event_type = "APPLICATION_RETRY_PENDING"
                    failure_reason = ver_res.message
                else:
                    target_status = ApplicationStatus.MANUAL_REVIEW.value
                    event_type = "TRANSITIONED_TO_MANUAL_REVIEW"
                    failure_reason = f"Verification failed with 0 max_retries: {ver_res.message}"
            else:  # PERSISTENT_FAILURE
                target_status = ApplicationStatus.FAILED.value
                event_type = "APPLICATION_FAILED"
                failure_reason = ver_res.message

        validate_state_transition(ApplicationStatus.PENDING.value, target_status)

        # 6. Atomic persistence of application and audit record
        request_id = submission.request_id or f"req-{uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        try:
            application = Application(
                request_id=request_id,
                workflow_id=submission.workflow_id,
                workflow_config_id=config.id,
                idempotency_key=submission.idempotency_key,
                payload_hash=payload_hash,
                input_data=submission.input_data,
                status=target_status,
                retry_count=0,
                created_at=now,
                updated_at=now,
            )
            db.add(application)
            db.flush()  # Obtain auto-generated application.id

            audit_details = {
                "status": decision.status,
                "application_status": target_status,
                "passed": decision.passed,
                "total_rules": decision.total_rules,
                "passed_rules": decision.passed_rules,
                "failed_rules": decision.failed_rules,
                "workflow_version": config.version,
                "retry_count": 0,
                "max_retries": max_retries,
                "failed_rule_ids": [r.rule_id for r in decision.results if not r.passed],
                "verification": {
                    "outcome": verification_outcome,
                    "message": failure_reason or "Verification successful",
                } if verification_outcome else None,
            }

            audit_log = AuditLog(
                application_id=application.id,
                event_type=event_type,
                previous_state=ApplicationStatus.PENDING.value,
                new_state=target_status,
                details=audit_details,
                created_at=now,
            )
            db.add(audit_log)

            db.commit()
            db.refresh(application)
        except IntegrityError:
            # Handle database-level concurrent idempotency collision
            db.rollback()
            racing_app = (
                db.query(Application)
                .filter(
                    Application.workflow_id == submission.workflow_id,
                    Application.idempotency_key == submission.idempotency_key,
                )
                .first()
            )
            if racing_app:
                if racing_app.payload_hash == payload_hash:
                    latest_audit = (
                        db.query(AuditLog)
                        .filter(AuditLog.application_id == racing_app.id)
                        .order_by(AuditLog.created_at.desc())
                        .first()
                    )
                    summary = _reconstruct_decision_summary_from_audit(latest_audit)
                    return ProcessedApplicationResult(
                        application=racing_app,
                        decision_summary=summary,
                        is_idempotent_replay=True,
                    )
                else:
                    raise IdempotencyConflictError(
                        f"Idempotency key '{submission.idempotency_key}' collision with different data."
                    )
            raise
        except Exception:
            db.rollback()
            raise

        decision_summary = _build_decision_summary_from_decision(decision)
        return ProcessedApplicationResult(
            application=application,
            decision_summary=decision_summary,
            is_idempotent_replay=False,
            verification_outcome=verification_outcome,
            failure_reason=failure_reason,
        )

    def retry_application(self, db: Session, application_id: int) -> ProcessedApplicationResult:
        """Retry an application currently in RETRY_PENDING status."""
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            raise ApplicationNotFoundError(f"Application with ID {application_id} not found.")

        # Check eligibility
        if not is_eligible_for_retry(application.status):
            raise IneligibleRetryError(
                f"Application {application_id} is in status '{application.status}' and cannot be retried. "
                "Only applications in 'RETRY_PENDING' are eligible for retry."
            )

        config = application.workflow_config
        max_retries = (
            config.config_data.get("max_retries", settings.max_retries)
            if (config and isinstance(config.config_data, dict))
            else settings.max_retries
        )

        # Check retry limit
        if application.retry_count >= max_retries:
            raise RetryLimitExceededError(
                f"Application {application_id} has exhausted all {max_retries} permitted retry attempts."
            )

        next_retry_count = application.retry_count + 1

        # Perform simulated verification OUTSIDE of database transaction
        input_data = dict(application.input_data)
        ver_res: VerificationResult = self.verifier.verify(input_data, retry_count=next_retry_count)
        verification_outcome = ver_res.outcome.value
        failure_reason: Optional[str] = None

        if ver_res.is_success:
            new_status = ApplicationStatus.APPROVED.value
            event_type = "RETRY_SUCCEEDED"
        elif ver_res.is_temporary_failure:
            if next_retry_count < max_retries:
                new_status = ApplicationStatus.RETRY_PENDING.value
                event_type = "RETRY_FAILED_TEMPORARY"
                failure_reason = ver_res.message
            else:
                new_status = ApplicationStatus.MANUAL_REVIEW.value
                event_type = "RETRY_EXHAUSTED_MANUAL_REVIEW"
                failure_reason = f"Max retries exhausted ({next_retry_count}/{max_retries}): {ver_res.message}"
        else:  # PERSISTENT_FAILURE
            new_status = ApplicationStatus.FAILED.value
            event_type = "RETRY_FAILED_PERSISTENT"
            failure_reason = ver_res.message

        validate_state_transition(application.status, new_status)

        # Atomic persistence of state change and audit log
        try:
            app_record = db.query(Application).filter(Application.id == application_id).first()
            if not app_record or not is_eligible_for_retry(app_record.status):
                raise IneligibleRetryError(
                    f"Application {application_id} state changed concurrently."
                )

            previous_state = app_record.status
            app_record.status = new_status
            app_record.retry_count = next_retry_count
            app_record.updated_at = datetime.now(timezone.utc)

            audit_details = {
                "retry_count": next_retry_count,
                "max_retries": max_retries,
                "status": new_status,
                "verification": {
                    "outcome": verification_outcome,
                    "message": failure_reason or "Verification successful on retry",
                },
            }

            audit_log = AuditLog(
                application_id=app_record.id,
                event_type=event_type,
                previous_state=previous_state,
                new_state=new_status,
                details=audit_details,
                created_at=datetime.now(timezone.utc),
            )
            db.add(audit_log)

            db.commit()
            db.refresh(app_record)
        except Exception:
            db.rollback()
            raise

        # Reconstruct decision summary for response
        rules_audit = (
            db.query(AuditLog)
            .filter(AuditLog.application_id == app_record.id)
            .order_by(AuditLog.id.asc())
            .first()
        )
        summary = _reconstruct_decision_summary_from_audit(rules_audit, current_status=app_record.status)

        return ProcessedApplicationResult(
            application=app_record,
            decision_summary=summary,
            is_idempotent_replay=False,
            verification_outcome=verification_outcome,
            failure_reason=failure_reason,
        )


orchestrator = WorkflowOrchestrator()
