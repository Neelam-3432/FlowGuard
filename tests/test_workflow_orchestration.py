"""Tests for workflow orchestration layer, configuration retrieval, and state management."""

import pytest
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.orchestration.exceptions import (
    InvalidStateTransitionError,
    InvalidWorkflowConfigError,
    WorkflowNotFoundError,
)
from app.orchestration.orchestrator import orchestrator
from app.orchestration.state import (
    ApplicationStatus,
    is_terminal_state,
    is_valid_transition,
    validate_state_transition,
)
from app.schemas.application import ApplicationCreateRequest
from app.services.workflow_config_service import (
    create_next_workflow_version,
    create_workflow_config,
)


@pytest.fixture
def loan_workflow_config(db_session: Session) -> None:
    """Create a sample active workflow configuration for loan approval."""
    config_data = {
        "version": "1.0",
        "description": "Loan Approval Rules",
        "rules": [
            {
                "rule_id": "REQ_NAME",
                "category": "mandatory",
                "field": "applicant_name",
            },
            {
                "rule_id": "MIN_AGE",
                "category": "threshold",
                "field": "applicant_age",
                "operator": "gte",
                "threshold": 18,
            },
            {
                "rule_id": "MIN_INCOME",
                "category": "threshold",
                "field": "annual_income",
                "operator": "gte",
                "threshold": 300000,
            },
        ],
    }
    create_workflow_config(
        db_session,
        workflow_id="loan_approval",
        version=1,
        config_data=config_data,
        is_active=True,
    )


def test_orchestration_approved_application(db_session: Session, loan_workflow_config: None) -> None:
    """Verify that an application meeting all rules transitions to APPROVED with audit logging."""
    submission = ApplicationCreateRequest(
        workflow_id="loan_approval",
        idempotency_key="loan-app-001",
        input_data={
            "applicant_name": "Alice Johnson",
            "applicant_age": 28,
            "annual_income": 450000,
        },
    )

    result = orchestrator.process_application(db_session, submission)

    assert result.is_idempotent_replay is False
    assert result.application.status == ApplicationStatus.APPROVED.value
    assert result.application.workflow_id == "loan_approval"
    assert result.decision_summary is not None
    assert result.decision_summary.passed is True
    assert result.decision_summary.status == "approved"
    assert result.decision_summary.passed_rules == 3
    assert result.decision_summary.failed_rules == 0

    # Verify audit log in database
    audit = db_session.query(AuditLog).filter_by(application_id=result.application.id).first()
    assert audit is not None
    assert audit.event_type == "APPLICATION_APPROVED"
    assert audit.previous_state == ApplicationStatus.PENDING.value
    assert audit.new_state == ApplicationStatus.APPROVED.value
    assert audit.details["passed"] is True


def test_orchestration_rejected_application(db_session: Session, loan_workflow_config: None) -> None:
    """Verify that an application failing a rule transitions to REJECTED."""
    submission = ApplicationCreateRequest(
        workflow_id="loan_approval",
        idempotency_key="loan-app-002",
        input_data={
            "applicant_name": "Bob",
            "applicant_age": 16,  # Fails threshold 18
            "annual_income": 500000,
        },
    )

    result = orchestrator.process_application(db_session, submission)

    assert result.application.status == ApplicationStatus.REJECTED.value
    assert result.decision_summary is not None
    assert result.decision_summary.passed is False
    assert result.decision_summary.failed_rules == 1

    # Verify audit log in database
    audit = db_session.query(AuditLog).filter_by(application_id=result.application.id).first()
    assert audit is not None
    assert audit.event_type == "APPLICATION_REJECTED"
    assert audit.new_state == ApplicationStatus.REJECTED.value
    assert "MIN_AGE" in audit.details["failed_rule_ids"]


def test_orchestration_missing_workflow_configuration(db_session: Session) -> None:
    """Verify that an unknown workflow_id raises WorkflowNotFoundError."""
    submission = ApplicationCreateRequest(
        workflow_id="non_existent_workflow",
        idempotency_key="app-unknown-001",
        input_data={"any": "value"},
    )

    with pytest.raises(WorkflowNotFoundError, match="not found"):
        orchestrator.process_application(db_session, submission)


def test_orchestration_invalid_workflow_configuration(db_session: Session) -> None:
    """Verify that malformed workflow configuration data raises InvalidWorkflowConfigError."""
    # Create invalid workflow config in DB (e.g. unknown operator)
    create_workflow_config(
        db_session,
        workflow_id="broken_workflow",
        version=1,
        config_data={
            "rules": [
                {
                    "rule_id": "INVALID_RULE",
                    "category": "threshold",
                    "field": "score",
                    "operator": "invalid_op",
                    "threshold": 100,
                }
            ]
        },
        is_active=True,
    )

    submission = ApplicationCreateRequest(
        workflow_id="broken_workflow",
        idempotency_key="app-broken-001",
        input_data={"score": 150},
    )

    with pytest.raises(InvalidWorkflowConfigError, match="invalid"):
        orchestrator.process_application(db_session, submission)


def test_orchestration_specific_version_selection(db_session: Session) -> None:
    """Verify selecting an older version of a workflow vs the latest active version."""
    # Version 1: threshold is 18
    v1 = create_workflow_config(
        db_session,
        workflow_id="versioned_workflow",
        version=1,
        config_data={
            "rules": [
                {"rule_id": "AGE_V1", "category": "threshold", "field": "age", "operator": "gte", "threshold": 18}
            ]
        },
        is_active=False,
    )
    # Version 2: threshold is 21
    v2 = create_workflow_config(
        db_session,
        workflow_id="versioned_workflow",
        version=2,
        config_data={
            "rules": [
                {"rule_id": "AGE_V2", "category": "threshold", "field": "age", "operator": "gte", "threshold": 21}
            ]
        },
        is_active=True,
    )

    app_data = {"age": 19}

    # Request specific v1 (should pass threshold 18)
    sub_v1 = ApplicationCreateRequest(
        workflow_id="versioned_workflow",
        workflow_version=1,
        idempotency_key="ver-app-1",
        input_data=app_data,
    )
    res_v1 = orchestrator.process_application(db_session, sub_v1)
    assert res_v1.application.status == ApplicationStatus.APPROVED.value
    assert res_v1.application.workflow_config_id == v1.id

    # Request default (active v2; should fail threshold 21)
    sub_v2 = ApplicationCreateRequest(
        workflow_id="versioned_workflow",
        idempotency_key="ver-app-2",
        input_data=app_data,
    )
    res_v2 = orchestrator.process_application(db_session, sub_v2)
    assert res_v2.application.status == ApplicationStatus.REJECTED.value
    assert res_v2.application.workflow_config_id == v2.id


def test_orchestration_intentionally_empty_rules_config(db_session: Session) -> None:
    """Verify that an intentionally empty rules list in config evaluates cleanly as approved."""
    create_workflow_config(
        db_session,
        workflow_id="empty_rules_wf",
        version=1,
        config_data={"rules": []},
        is_active=True,
    )

    submission = ApplicationCreateRequest(
        workflow_id="empty_rules_wf",
        idempotency_key="empty-app-1",
        input_data={"data": 123},
    )

    result = orchestrator.process_application(db_session, submission)
    assert result.application.status == ApplicationStatus.APPROVED.value
    assert result.decision_summary is not None
    assert result.decision_summary.total_rules == 0
    assert result.decision_summary.passed is True


def test_state_transitions_logic() -> None:
    """Verify state transition validation rules."""
    # Valid transitions from PENDING
    assert is_valid_transition(ApplicationStatus.PENDING.value, ApplicationStatus.APPROVED.value) is True
    assert is_valid_transition(ApplicationStatus.PENDING.value, ApplicationStatus.REJECTED.value) is True
    assert is_valid_transition(ApplicationStatus.PENDING.value, ApplicationStatus.FAILED.value) is True

    # Invalid transitions
    assert is_valid_transition(ApplicationStatus.APPROVED.value, ApplicationStatus.PENDING.value) is False
    assert is_valid_transition(ApplicationStatus.REJECTED.value, ApplicationStatus.APPROVED.value) is False
    assert is_valid_transition(ApplicationStatus.APPROVED.value, ApplicationStatus.REJECTED.value) is False

    # Validation function
    validate_state_transition(ApplicationStatus.PENDING.value, ApplicationStatus.APPROVED.value)
    with pytest.raises(InvalidStateTransitionError):
        validate_state_transition(ApplicationStatus.APPROVED.value, ApplicationStatus.PENDING.value)

    # Terminal state checks
    assert is_terminal_state(ApplicationStatus.APPROVED.value) is True
    assert is_terminal_state(ApplicationStatus.REJECTED.value) is True
    assert is_terminal_state(ApplicationStatus.FAILED.value) is True
    assert is_terminal_state(ApplicationStatus.PENDING.value) is False

