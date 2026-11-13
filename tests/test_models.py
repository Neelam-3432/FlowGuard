"""Tests for SQLAlchemy models: insertion, relationships, constraints, and immutability."""

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.models.workflow_config import WorkflowConfig


def test_successful_record_insertion(db_session: Session) -> None:
    """Verify that records for all three models can be inserted and queried successfully."""
    # 1. Insert WorkflowConfig
    config = WorkflowConfig(
        workflow_id="loan_approval",
        version=1,
        config_data={"max_amount": 50000, "min_credit_score": 650},
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()
    db_session.refresh(config)

    assert config.id is not None
    assert config.workflow_id == "loan_approval"
    assert config.version == 1
    assert config.config_data["max_amount"] == 50000
    assert config.is_active is True
    assert config.created_at is not None

    # 2. Insert Application
    application = Application(
        request_id="req-1001",
        workflow_id="loan_approval",
        workflow_config_id=config.id,
        idempotency_key="idemp-key-001",
        payload_hash="hash_abc_123",
        input_data={"applicant_name": "Alice", "requested_amount": 25000},
        status="PENDING",
        retry_count=0,
    )
    db_session.add(application)
    db_session.commit()
    db_session.refresh(application)

    assert application.id is not None
    assert application.request_id == "req-1001"
    assert application.workflow_config_id == config.id
    assert application.status == "PENDING"
    assert application.created_at is not None
    assert application.updated_at is not None

    # 3. Insert AuditLog
    audit = AuditLog(
        application_id=application.id,
        event_type="SUBMITTED",
        previous_state=None,
        new_state="PENDING",
        details={"source": "api_gateway"},
    )
    db_session.add(audit)
    db_session.commit()
    db_session.refresh(audit)

    assert audit.id is not None
    assert audit.application_id == application.id
    assert audit.event_type == "SUBMITTED"
    assert audit.new_state == "PENDING"
    assert audit.details["source"] == "api_gateway"
    assert audit.created_at is not None


def test_application_and_audit_relationship(db_session: Session) -> None:
    """Verify bidirectional relationships between Application, AuditLog, and WorkflowConfig."""
    config = WorkflowConfig(
        workflow_id="fraud_check",
        version=1,
        config_data={"threshold": 0.85},
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()

    application = Application(
        request_id="req-2001",
        workflow_id="fraud_check",
        workflow_config_id=config.id,
        idempotency_key="idemp-key-2001",
        payload_hash="hash_fraud_001",
        input_data={"amount": 100},
        status="PENDING",
    )
    db_session.add(application)
    db_session.commit()

    # Add audit logs via application relationship
    audit1 = AuditLog(
        application_id=application.id,
        event_type="APPLICATION_CREATED",
        previous_state=None,
        new_state="PENDING",
        details={"info": "Initial creation"},
    )
    audit2 = AuditLog(
        application_id=application.id,
        event_type="STATUS_UPDATED",
        previous_state="PENDING",
        new_state="APPROVED",
        details={"info": "Passed fraud score"},
    )
    db_session.add_all([audit1, audit2])
    db_session.commit()
    db_session.refresh(application)

    # Verify Application -> AuditLogs
    assert len(application.audit_logs) == 2
    assert application.audit_logs[0].event_type == "APPLICATION_CREATED"
    assert application.audit_logs[1].event_type == "STATUS_UPDATED"

    # Verify AuditLog -> Application back-reference
    assert audit1.application.id == application.id
    assert audit1.application.request_id == "req-2001"

    # Verify WorkflowConfig -> Applications relationship
    db_session.refresh(config)
    assert len(config.applications) == 1
    assert config.applications[0].id == application.id
    assert application.workflow_config.id == config.id


def test_foreign_key_enforcement_invalid_workflow_config_id(db_session: Session) -> None:
    """Verify that inserting an Application with an invalid workflow_config_id fails via FK constraint."""
    invalid_app = Application(
        request_id="req-invalid-fk",
        workflow_id="loan_approval",
        workflow_config_id=99999,  # Non-existent FK
        idempotency_key="idemp-fk-01",
        payload_hash="hash_001",
        input_data={"test": 123},
        status="PENDING",
    )
    db_session.add(invalid_app)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_foreign_key_enforcement_invalid_application_id_for_audit(db_session: Session) -> None:
    """Verify that inserting an AuditLog with an invalid application_id fails via FK constraint."""
    invalid_audit = AuditLog(
        application_id=99999,  # Non-existent FK
        event_type="INVALID_EVENT",
        previous_state=None,
        new_state="PENDING",
        details={},
    )
    db_session.add(invalid_audit)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_foreign_key_restrict_on_workflow_config_delete(db_session: Session) -> None:
    """Verify that a WorkflowConfig referenced by an Application cannot be deleted (RESTRICT)."""
    config = WorkflowConfig(
        workflow_id="kyc_verification",
        version=1,
        config_data={"strict_mode": True},
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()

    application = Application(
        request_id="req-kyc-01",
        workflow_id="kyc_verification",
        workflow_config_id=config.id,
        idempotency_key="idemp-kyc-01",
        payload_hash="hash_kyc_01",
        input_data={"document_type": "passport"},
        status="PENDING",
    )
    db_session.add(application)
    db_session.commit()

    # Attempt to delete the parent config
    db_session.delete(config)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_cascade_delete_application_deletes_audit_logs(db_session: Session) -> None:
    """Verify that deleting an Application cascades to delete all its associated AuditLogs."""
    config = WorkflowConfig(
        workflow_id="auto_underwrite",
        version=1,
        config_data={},
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()

    application = Application(
        request_id="req-cascade-01",
        workflow_id="auto_underwrite",
        workflow_config_id=config.id,
        idempotency_key="idemp-cascade-01",
        payload_hash="hash_cascade_01",
        input_data={"score": 720},
        status="PENDING",
    )
    db_session.add(application)
    db_session.commit()

    audit = AuditLog(
        application_id=application.id,
        event_type="CREATED",
        previous_state=None,
        new_state="PENDING",
        details={},
    )
    db_session.add(audit)
    db_session.commit()

    audit_id = audit.id
    assert db_session.get(AuditLog, audit_id) is not None

    # Delete application
    db_session.delete(application)
    db_session.commit()

    # AuditLog should now be deleted via cascade
    assert db_session.get(AuditLog, audit_id) is None


def test_unique_constraint_workflow_config_version(db_session: Session) -> None:
    """Verify that (workflow_id, version) must be unique on WorkflowConfig."""
    config1 = WorkflowConfig(
        workflow_id="scoring_engine",
        version=1,
        config_data={"version_note": "First release"},
        is_active=True,
    )
    db_session.add(config1)
    db_session.commit()

    # Attempt to insert identical (workflow_id, version)
    duplicate_config = WorkflowConfig(
        workflow_id="scoring_engine",
        version=1,
        config_data={"version_note": "Duplicate attempt"},
        is_active=False,
    )
    db_session.add(duplicate_config)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_unique_constraint_application_idempotency(db_session: Session) -> None:
    """Verify that (workflow_id, idempotency_key) must be unique on Application."""
    config = WorkflowConfig(
        workflow_id="payments",
        version=1,
        config_data={},
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()

    app1 = Application(
        request_id="req-pay-1",
        workflow_id="payments",
        workflow_config_id=config.id,
        idempotency_key="idem-key-999",
        payload_hash="hash_999",
        input_data={"amount": 500},
        status="PENDING",
    )
    db_session.add(app1)
    db_session.commit()

    duplicate_app = Application(
        request_id="req-pay-2",
        workflow_id="payments",
        workflow_config_id=config.id,
        idempotency_key="idem-key-999",  # Duplicate idempotency_key for same workflow
        payload_hash="hash_999_dup",
        input_data={"amount": 500},
        status="PENDING",
    )
    db_session.add(duplicate_app)

    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_prevent_accidental_modification_of_historical_config(db_session: Session) -> None:
    """Verify that historical WorkflowConfig versions cannot be modified."""
    config = WorkflowConfig(
        workflow_id="credit_risk",
        version=1,
        config_data={"threshold": 700},
        is_active=True,
    )
    db_session.add(config)
    db_session.commit()

    # Attempting to modify config_data must raise ValueError
    config.config_data = {"threshold": 650}
    with pytest.raises(ValueError, match="immutable"):
        db_session.commit()
    db_session.rollback()

    # Verify is_active CAN be toggled (deactivation) without altering config_data
    config = db_session.get(WorkflowConfig, config.id)
    assert config is not None
    config.is_active = False
    db_session.commit()
    db_session.refresh(config)
    assert config.is_active is False
    assert config.config_data == {"threshold": 700}

