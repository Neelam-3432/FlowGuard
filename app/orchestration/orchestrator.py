"""Workflow Orchestrator managing application execution lifecycle."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import uuid4
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.workflow_config import WorkflowConfig
from app.orchestration.exceptions import (
    IdempotencyConflictError,
    InvalidWorkflowConfigError,
    WorkflowNotFoundError,
)
from app.orchestration.state import ApplicationStatus, validate_state_transition
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


def _reconstruct_decision_summary_from_audit(audit_log: Optional[AuditLog]) -> Optional[DecisionSummaryResponse]:
    """Reconstruct a decision summary from stored audit log details for idempotent replays."""
    if not audit_log or not audit_log.details:
        return None

    details = audit_log.details
    return DecisionSummaryResponse(
        status=details.get("status", "unknown"),
        passed=details.get("passed", False),
        total_rules=details.get("total_rules", 0),
        passed_rules=details.get("passed_rules", 0),
        failed_rules=details.get("failed_rules", 0),
        results=[],
        metadata={"replayed": True, "workflow_version": details.get("workflow_version")},
    )


@dataclass
class ProcessedApplicationResult:
    """Container holding application entity, decision summary, and idempotent replay flag."""

    application: Application
    decision_summary: Optional[DecisionSummaryResponse]
    is_idempotent_replay: bool = False

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
            decision=self.decision_summary,
            created_at=self.application.created_at,
            updated_at=self.application.updated_at,
        )


class WorkflowOrchestrator:
    """Orchestrates application evaluation, state transitions, idempotency, and atomic persistence."""

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
                    .order_by(AuditLog.created_at.desc())
                    .first()
                )
                summary = _reconstruct_decision_summary_from_audit(latest_audit)
                return ProcessedApplicationResult(
                    application=existing,
                    decision_summary=summary,
                    is_idempotent_replay=True,
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

        # 5. Determine resulting application status and validate state transition
        if decision.passed:
            target_status = ApplicationStatus.APPROVED.value
            event_type = "APPLICATION_APPROVED"
        else:
            target_status = ApplicationStatus.REJECTED.value
            event_type = "APPLICATION_REJECTED"

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
                "passed": decision.passed,
                "total_rules": decision.total_rules,
                "passed_rules": decision.passed_rules,
                "failed_rules": decision.failed_rules,
                "workflow_version": config.version,
                "failed_rule_ids": [r.rule_id for r in decision.results if not r.passed],
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
        )


orchestrator = WorkflowOrchestrator()

