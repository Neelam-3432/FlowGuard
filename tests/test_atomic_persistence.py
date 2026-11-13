"""Tests for atomic persistence, database rollback, and audit log integrity in orchestration."""

import pytest
from unittest.mock import patch
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.orchestration.orchestrator import orchestrator
from app.schemas.application import ApplicationCreateRequest
from app.services.workflow_config_service import create_workflow_config


@pytest.fixture
def atomic_workflow(db_session: Session) -> None:
    """Fixture providing a sample workflow for atomic transaction testing."""
    create_workflow_config(
        db_session,
        workflow_id="atomic_wf",
        version=1,
        config_data={
            "rules": [
                {"rule_id": "REQ_VAL", "category": "mandatory", "field": "val"}
            ]
        },
        is_active=True,
    )


def test_atomic_persistence_both_committed(db_session: Session, atomic_workflow: None) -> None:
    """Verify that both Application and AuditLog are committed together in a single transaction."""
    submission = ApplicationCreateRequest(
        workflow_id="atomic_wf",
        idempotency_key="atomic-key-001",
        input_data={"val": "sample_data"},
    )

    result = orchestrator.process_application(db_session, submission)
    app_id = result.application.id

    # Verify both records exist in DB
    app = db_session.get(Application, app_id)
    assert app is not None
    assert app.status == "APPROVED"

    audits = db_session.query(AuditLog).filter_by(application_id=app_id).all()
    assert len(audits) == 1
    assert audits[0].event_type == "APPLICATION_APPROVED"
    assert audits[0].new_state == "APPROVED"


def test_transaction_rollback_when_audit_fails(db_session: Session, atomic_workflow: None) -> None:
    """Verify that if an error occurs during audit persistence, the application is rolled back completely."""
    submission = ApplicationCreateRequest(
        workflow_id="atomic_wf",
        idempotency_key="atomic-fail-key",
        input_data={"val": "sample_data"},
    )

    # Mock AuditLog initialization to trigger an unexpected error
    with patch("app.orchestration.orchestrator.AuditLog", side_effect=RuntimeError("Simulated audit creation failure")):
        with pytest.raises(RuntimeError, match="Simulated audit creation failure"):
            orchestrator.process_application(db_session, submission)

    # Verify no partial application was persisted
    persisted_app = db_session.query(Application).filter_by(
        workflow_id="atomic_wf",
        idempotency_key="atomic-fail-key"
    ).first()
    assert persisted_app is None, "Application must not be persisted if transaction failed"

    # Verify no orphan audit logs exist
    audit_count = db_session.query(AuditLog).count()
    assert audit_count == 0


def test_audit_log_captures_correct_metadata(db_session: Session, atomic_workflow: None) -> None:
    """Verify audit log records workflow version, status, and does not leak confidential input values."""
    secret_payload = {"val": "valid_value", "confidential_token": "secret_xyz_999"}
    submission = ApplicationCreateRequest(
        workflow_id="atomic_wf",
        idempotency_key="meta-check-key",
        input_data=secret_payload,
    )

    result = orchestrator.process_application(db_session, submission)
    audit = db_session.query(AuditLog).filter_by(application_id=result.application.id).first()

    assert audit is not None
    assert audit.details["workflow_version"] == 1
    assert audit.details["status"] == "approved"
    assert audit.details["passed"] is True

    # Confidential input payload is not dumped in audit details
    details_str = str(audit.details)
    assert "secret_xyz_999" not in details_str
    assert "confidential_token" not in details_str

