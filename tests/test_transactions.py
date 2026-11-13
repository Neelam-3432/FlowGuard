"""Tests for atomic transactions, service operations, and rollback guarantees."""

import pytest
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.workflow_config import WorkflowConfig
from app.services.application_service import (
    create_application_with_audit,
    update_application_status_with_audit,
)
from app.services.workflow_config_service import (
    create_workflow_config,
    create_next_workflow_version,
    get_active_workflow_config,
    deactivate_workflow_config,
)


def test_atomic_application_creation_with_audit(db_session: Session) -> None:
    """Verify that an Application and its initial AuditLog are created atomically."""
    config = create_workflow_config(
        db_session,
        workflow_id="order_processing",
        version=1,
        config_data={"cutoff_time": "18:00"},
    )

    app, audit = create_application_with_audit(
        db_session,
        request_id="req-order-1",
        workflow_id="order_processing",
        workflow_config_id=config.id,
        idempotency_key="idem-order-1",
        payload_hash="sha256_hash_1",
        input_data={"order_id": "ORD-123", "total": 199.99},
        initial_status="PENDING",
    )

    assert app.id is not None
    assert audit.id is not None
    assert audit.application_id == app.id
    assert audit.event_type == "APPLICATION_CREATED"
    assert audit.new_state == "PENDING"
    assert app.status == "PENDING"

    # Confirm both records exist in DB
    assert db_session.get(Application, app.id) is not None
    assert db_session.get(AuditLog, audit.id) is not None


def test_atomic_update_status_and_audit_success(db_session: Session) -> None:
    """Verify that application status update and its audit log record commit together atomically."""
    config = create_workflow_config(
        db_session,
        workflow_id="underwriting",
        version=1,
        config_data={"rule": "auto_approve"},
    )

    app, _ = create_application_with_audit(
        db_session,
        request_id="req-underwrite-1",
        workflow_id="underwriting",
        workflow_config_id=config.id,
        idempotency_key="idem-uw-1",
        payload_hash="sha256_hash_uw",
        input_data={"income": 100000},
        initial_status="PENDING",
    )

    app_id = app.id

    # Update status to APPROVED with an audit record
    updated_app, new_audit = update_application_status_with_audit(
        db_session,
        application_id=app_id,
        new_status="APPROVED",
        event_type="DECISION_APPROVED",
        details={"score": 810, "notes": "Criteria satisfied"},
    )

    assert updated_app.status == "APPROVED"
    assert new_audit.event_type == "DECISION_APPROVED"
    assert new_audit.previous_state == "PENDING"
    assert new_audit.new_state == "APPROVED"
    assert new_audit.details["score"] == 810

    # Verify state in database
    db_session.expire_all()
    reloaded_app = db_session.get(Application, app_id)
    assert reloaded_app is not None
    assert reloaded_app.status == "APPROVED"
    assert len(reloaded_app.audit_logs) == 2


def test_transaction_rollback_when_operation_fails(db_session: Session) -> None:
    """Verify that if an error occurs during an update, neither the application status

    nor the audit record is committed, leaving the database completely clean.
    """
    config = create_workflow_config(
        db_session,
        workflow_id="claims_processing",
        version=1,
        config_data={"auto_pay_limit": 500},
    )

    app, initial_audit = create_application_with_audit(
        db_session,
        request_id="req-claim-1",
        workflow_id="claims_processing",
        workflow_config_id=config.id,
        idempotency_key="idem-claim-1",
        payload_hash="sha256_hash_claim",
        input_data={"amount": 450},
        initial_status="PENDING",
    )

    app_id = app.id
    initial_audit_id = initial_audit.id

    # Count audit logs before the failed update
    initial_audit_count = db_session.query(AuditLog).filter(AuditLog.application_id == app_id).count()
    assert initial_audit_count == 1

    # Attempt an update that triggers a failure prior to commit
    with pytest.raises(RuntimeError, match="Simulated failure triggered before transaction commit"):
        update_application_status_with_audit(
            db_session,
            application_id=app_id,
            new_status="PAID",
            event_type="DISBURSEMENT",
            details={"gateway": "stripe"},
            simulate_failure=True,
        )

    # Verify rollback: application status must still be 'PENDING'
    db_session.expire_all()
    persisted_app = db_session.get(Application, app_id)
    assert persisted_app is not None
    assert persisted_app.status == "PENDING", "Status must remain PENDING after rollback"

    # Verify rollback: no new audit log should be present in the database
    current_audit_count = db_session.query(AuditLog).filter(AuditLog.application_id == app_id).count()
    assert current_audit_count == 1, "Audit log count must remain 1 after rollback"

    all_audits = db_session.query(AuditLog).filter(AuditLog.application_id == app_id).all()
    assert len(all_audits) == 1
    assert all_audits[0].id == initial_audit_id
    assert all_audits[0].event_type == "APPLICATION_CREATED"


def test_workflow_config_version_uniqueness_and_management(db_session: Session) -> None:
    """Verify workflow configuration version uniqueness and lifecycle management."""
    # 1. Create version 1
    v1 = create_workflow_config(
        db_session,
        workflow_id="insurance_quote",
        version=1,
        config_data={"base_rate": 100},
        is_active=True,
    )
    assert v1.version == 1
    assert v1.is_active is True

    # 2. Attempting to create duplicate version 1 raises ValueError
    with pytest.raises(ValueError, match="already exists"):
        create_workflow_config(
            db_session,
            workflow_id="insurance_quote",
            version=1,
            config_data={"base_rate": 150},
        )

    # 3. Create next version automatically (increments to version 2 and deactivates version 1)
    v2 = create_next_workflow_version(
        db_session,
        workflow_id="insurance_quote",
        config_data={"base_rate": 120},
        set_active=True,
    )
    assert v2.version == 2
    assert v2.is_active is True

    # Verify v1 is now deactivated
    db_session.refresh(v1)
    assert v1.is_active is False

    # 4. Query active configuration
    active_config = get_active_workflow_config(db_session, "insurance_quote")
    assert active_config is not None
    assert active_config.id == v2.id
    assert active_config.version == 2
    assert active_config.config_data["base_rate"] == 120

    # 5. Deactivate active config
    deactivate_workflow_config(db_session, v2.id)
    db_session.refresh(v2)
    assert v2.is_active is False

    # Now no active config exists
    assert get_active_workflow_config(db_session, "insurance_quote") is None

