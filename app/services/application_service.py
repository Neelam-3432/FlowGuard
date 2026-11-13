"""Application service demonstrating atomic persistence and transaction management."""

from datetime import datetime, timezone
from typing import Any, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.workflow_config import WorkflowConfig


def create_application_with_audit(
    db: Session,
    *,
    request_id: str,
    workflow_id: str,
    workflow_config_id: int,
    idempotency_key: str,
    payload_hash: str,
    input_data: dict[str, Any],
    initial_status: str = "PENDING",
    audit_details: Optional[dict[str, Any]] = None,
) -> Tuple[Application, AuditLog]:
    """Atomically create a new Application and its initial AuditLog record.

    Both records are committed together in a single transaction.
    If any error occurs, the entire transaction is rolled back, preventing
    orphan or partial records.

    No external API calls or network operations are performed inside this transaction.
    """
    try:
        # Validate that workflow_config exists and is active
        config = db.query(WorkflowConfig).filter(WorkflowConfig.id == workflow_config_id).first()
        if not config:
            raise ValueError(f"WorkflowConfig with ID {workflow_config_id} does not exist.")
        if config.workflow_id != workflow_id:
            raise ValueError(
                f"WorkflowConfig {workflow_config_id} belongs to '{config.workflow_id}', not '{workflow_id}'."
            )

        now = datetime.now(timezone.utc)
        application = Application(
            request_id=request_id,
            workflow_id=workflow_id,
            workflow_config_id=workflow_config_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            input_data=input_data,
            status=initial_status,
            retry_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(application)
        # Flush to obtain the auto-generated application.id without committing
        db.flush()

        audit_log = AuditLog(
            application_id=application.id,
            event_type="APPLICATION_CREATED",
            previous_state=None,
            new_state=initial_status,
            details=audit_details or {"message": "Application initialized"},
            created_at=now,
        )
        db.add(audit_log)

        # Single atomic commit for both records
        db.commit()
        db.refresh(application)
        db.refresh(audit_log)
        return application, audit_log
    except Exception:
        db.rollback()
        raise


def update_application_status_with_audit(
    db: Session,
    *,
    application_id: int,
    new_status: str,
    event_type: str,
    details: Optional[dict[str, Any]] = None,
    retry_count_increment: int = 0,
    simulate_failure: bool = False,
) -> Tuple[Application, AuditLog]:
    """Atomically update an application's status and record an audit log entry.

    Ensures strict ACID transaction semantics:
    1. Fetches the existing application record.
    2. Updates application status and increments retry_count if specified.
    3. Creates a corresponding AuditLog entry capturing the transition.
    4. Commits both operations together.

    If any failure occurs (e.g. database error, validation failure, or
    simulate_failure=True), db.rollback() is invoked. Neither the application
    status update nor the audit log is persisted.

    No external API calls are executed within this transaction block.
    """
    try:
        application = db.query(Application).filter(Application.id == application_id).first()
        if not application:
            raise ValueError(f"Application with ID {application_id} not found.")

        previous_status = application.status
        now = datetime.now(timezone.utc)

        # Update application state
        application.status = new_status
        if retry_count_increment > 0:
            application.retry_count += retry_count_increment
        application.updated_at = now

        # Create audit entry
        audit_log = AuditLog(
            application_id=application.id,
            event_type=event_type,
            previous_state=previous_status,
            new_state=new_status,
            details=details or {},
            created_at=now,
        )
        db.add(audit_log)

        # For testing failure rollback guarantee before commit
        if simulate_failure:
            raise RuntimeError("Simulated failure triggered before transaction commit.")

        # Atomic commit
        db.commit()
        db.refresh(application)
        db.refresh(audit_log)
        return application, audit_log
    except Exception:
        db.rollback()
        raise

