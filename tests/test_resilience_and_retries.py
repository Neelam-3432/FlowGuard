"""Tests for Phase 4: Resilience, Retries, Idempotency, and External Verification."""

from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.orchestration.exceptions import (
    ApplicationNotFoundError,
    IneligibleRetryError,
    RetryLimitExceededError,
)
from app.orchestration.orchestrator import WorkflowOrchestrator, orchestrator
from app.orchestration.state import ApplicationStatus
from app.schemas.application import ApplicationCreateRequest
from app.services.workflow_config_service import create_workflow_config
from app.verification.simulator import (
    ExternalVerificationSimulator,
    VerificationOutcome,
    VerificationResult,
)


@pytest.fixture
def phase4_workflow(db_session: Session) -> str:
    """Fixture to configure a workflow supporting custom retry limits."""
    wf_id = "resilience_wf"
    create_workflow_config(
        db_session,
        workflow_id=wf_id,
        version=1,
        config_data={
            "max_retries": 3,
            "rules": [
                {
                    "rule_id": "REQ_NAME",
                    "category": "mandatory",
                    "field": "applicant_name",
                },
                {
                    "rule_id": "MIN_CREDIT",
                    "category": "threshold",
                    "field": "credit_score",
                    "operator": "gte",
                    "threshold": 650,
                },
            ],
        },
        is_active=True,
    )
    return wf_id


# ---------------------------------------------------------------------------
# 1. External Verification Simulator Unit Tests
# ---------------------------------------------------------------------------

def test_simulator_default_success() -> None:
    """Test simulator returns SUCCESS when no simulation directive is provided."""
    sim = ExternalVerificationSimulator()
    result = sim.verify({"applicant_name": "Alice", "credit_score": 700})
    assert result.is_success
    assert result.outcome == VerificationOutcome.SUCCESS
    assert "succeeded" in result.message.lower()


def test_simulator_persistent_failure() -> None:
    """Test simulator returns PERSISTENT_FAILURE on directive."""
    sim = ExternalVerificationSimulator()
    result = sim.verify({"simulated_verification": "PERSISTENT_FAILURE"})
    assert result.is_persistent_failure
    assert result.outcome == VerificationOutcome.PERSISTENT_FAILURE
    assert "persistent" in result.message.lower()


def test_simulator_temporary_failure_and_recovery() -> None:
    """Test simulator transient recovery using fail_until_retry."""
    sim = ExternalVerificationSimulator()
    data = {
        "simulated_verification": "TEMPORARY_FAILURE",
        "fail_until_retry": 2,
    }

    # retry_count = 0 -> failure
    res0 = sim.verify(data, retry_count=0)
    assert res0.is_temporary_failure

    # retry_count = 1 -> failure
    res1 = sim.verify(data, retry_count=1)
    assert res1.is_temporary_failure

    # retry_count = 2 -> recovered to SUCCESS
    res2 = sim.verify(data, retry_count=2)
    assert res2.is_success
    assert res2.details["recovered"] is True


def test_simulator_temporary_once_convenience() -> None:
    """Test simulator TEMPORARY_ONCE directive recovers on first retry."""
    sim = ExternalVerificationSimulator()
    data = {"simulated_verification": "TEMPORARY_ONCE"}

    res0 = sim.verify(data, retry_count=0)
    assert res0.is_temporary_failure

    res1 = sim.verify(data, retry_count=1)
    assert res1.is_success


# ---------------------------------------------------------------------------
# 2. Scenario 1: Successful Verification
# ---------------------------------------------------------------------------

def test_successful_verification_flow(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Successful business rules and verification directly transition to APPROVED."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-succ-01",
        "input_data": {
            "applicant_name": "John Doe",
            "credit_score": 750,
            "simulated_verification": "SUCCESS",
        },
    }

    response = client.post("/api/v1/applications/", json=payload)
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == ApplicationStatus.APPROVED.value
    assert body["retry_count"] == 0
    assert body["verification_outcome"] == VerificationOutcome.SUCCESS.value
    assert body["failure_reason"] is None
    assert body["decision"]["passed"] is True

    # Check Audit Log
    app = db_session.query(Application).filter_by(id=body["id"]).first()
    assert app is not None
    assert app.status == ApplicationStatus.APPROVED.value

    audits = db_session.query(AuditLog).filter_by(application_id=app.id).all()
    assert len(audits) == 1
    assert audits[0].event_type == "APPLICATION_APPROVED"
    assert audits[0].new_state == ApplicationStatus.APPROVED.value


# ---------------------------------------------------------------------------
# 3. Scenario 2: Temporary External Verification Failure
# ---------------------------------------------------------------------------

def test_temporary_failure_moves_to_retry_pending(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Temporary external verification failure transitions application to RETRY_PENDING."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-temp-01",
        "input_data": {
            "applicant_name": "Jane Doe",
            "credit_score": 720,
            "simulated_verification": "TEMPORARY_FAILURE",
        },
    }

    response = client.post("/api/v1/applications/", json=payload)
    assert response.status_code == 201
    body = response.json()

    assert body["status"] == ApplicationStatus.RETRY_PENDING.value
    assert body["retry_count"] == 0
    assert body["verification_outcome"] == VerificationOutcome.TEMPORARY_FAILURE.value
    assert "timeout" in body["failure_reason"].lower() or "temporary" in body["failure_reason"].lower()

    # Check Audit Log
    audits = db_session.query(AuditLog).filter_by(application_id=body["id"]).all()
    assert len(audits) == 1
    assert audits[0].event_type == "APPLICATION_RETRY_PENDING"
    assert audits[0].new_state == ApplicationStatus.RETRY_PENDING.value
    assert audits[0].details["retry_count"] == 0
    assert audits[0].details["max_retries"] == 3


# ---------------------------------------------------------------------------
# 4. Scenario 3: Successful Retry After Temporary Failure
# ---------------------------------------------------------------------------

def test_successful_retry_after_temporary_failure(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """An application in RETRY_PENDING successfully transitions to APPROVED upon retry."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-recovery-01",
        "input_data": {
            "applicant_name": "Sam Recovery",
            "credit_score": 710,
            "simulated_verification": "TEMPORARY_ONCE",
        },
    }

    # Initial submission: fails temporarily
    res_sub = client.post("/api/v1/applications/", json=payload)
    assert res_sub.status_code == 201
    app_id = res_sub.json()["id"]
    assert res_sub.json()["status"] == ApplicationStatus.RETRY_PENDING.value
    assert res_sub.json()["retry_count"] == 0

    # Retry submission: TEMPORARY_ONCE recovers at retry_count == 1
    res_retry = client.post(f"/api/v1/applications/{app_id}/retry")
    assert res_retry.status_code == 200
    retry_body = res_retry.json()

    assert retry_body["id"] == app_id
    assert retry_body["status"] == ApplicationStatus.APPROVED.value
    assert retry_body["retry_count"] == 1
    assert retry_body["verification_outcome"] == VerificationOutcome.SUCCESS.value
    assert retry_body["decision"]["passed"] is True

    # Audit records verification
    audits = (
        db_session.query(AuditLog)
        .filter_by(application_id=app_id)
        .order_by(AuditLog.id.asc())
        .all()
    )
    assert len(audits) == 2
    assert audits[0].event_type == "APPLICATION_RETRY_PENDING"
    assert audits[1].event_type == "RETRY_SUCCEEDED"
    assert audits[1].previous_state == ApplicationStatus.RETRY_PENDING.value
    assert audits[1].new_state == ApplicationStatus.APPROVED.value
    assert audits[1].details["retry_count"] == 1


# ---------------------------------------------------------------------------
# 5. Scenario 4 & 5: Multi-step Retries & Transition to MANUAL_REVIEW
# ---------------------------------------------------------------------------

def test_retry_exhaustion_transitions_to_manual_review(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Application transitions to MANUAL_REVIEW after exhausting max_retries."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-exhaust-01",
        "input_data": {
            "applicant_name": "Persistent Timeout User",
            "credit_score": 680,
            "simulated_verification": "TEMPORARY_FAILURE",  # Always temporary failure
        },
    }

    # Initial submission (max_retries is 3 for phase4_workflow)
    res0 = client.post("/api/v1/applications/", json=payload)
    assert res0.status_code == 201
    app_id = res0.json()["id"]
    assert res0.json()["status"] == ApplicationStatus.RETRY_PENDING.value
    assert res0.json()["retry_count"] == 0

    # Retry 1 (1/3)
    res1 = client.post(f"/api/v1/applications/{app_id}/retry")
    assert res1.status_code == 200
    assert res1.json()["status"] == ApplicationStatus.RETRY_PENDING.value
    assert res1.json()["retry_count"] == 1

    # Retry 2 (2/3)
    res2 = client.post(f"/api/v1/applications/{app_id}/retry")
    assert res2.status_code == 200
    assert res2.json()["status"] == ApplicationStatus.RETRY_PENDING.value
    assert res2.json()["retry_count"] == 2

    # Retry 3 (3/3: max reached -> transitions to MANUAL_REVIEW)
    res3 = client.post(f"/api/v1/applications/{app_id}/retry")
    assert res3.status_code == 200
    data3 = res3.json()
    assert data3["status"] == ApplicationStatus.MANUAL_REVIEW.value
    assert data3["retry_count"] == 3
    assert "exhausted" in data3["failure_reason"].lower()

    # Retry 4 (Exhausted attempt: must be rejected with 400 Bad Request)
    res4 = client.post(f"/api/v1/applications/{app_id}/retry")
    assert res4.status_code == 400
    assert "cannot be retried" in res4.json()["detail"].lower()

    # Verify audit log trail
    audits = (
        db_session.query(AuditLog)
        .filter_by(application_id=app_id)
        .order_by(AuditLog.id.asc())
        .all()
    )
    assert len(audits) == 4
    assert audits[0].event_type == "APPLICATION_RETRY_PENDING"
    assert audits[1].event_type == "RETRY_FAILED_TEMPORARY"
    assert audits[2].event_type == "RETRY_FAILED_TEMPORARY"
    assert audits[3].event_type == "RETRY_EXHAUSTED_MANUAL_REVIEW"
    assert audits[3].new_state == ApplicationStatus.MANUAL_REVIEW.value


# ---------------------------------------------------------------------------
# 6. Scenario 6: Permanent Verification Failure
# ---------------------------------------------------------------------------

def test_permanent_verification_failure_without_retry(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Permanent verification failures move to FAILED immediately without retry eligibility."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-perm-fail-01",
        "input_data": {
            "applicant_name": "Fraud Suspect",
            "credit_score": 790,
            "simulated_verification": "PERSISTENT_FAILURE",
        },
    }

    res = client.post("/api/v1/applications/", json=payload)
    assert res.status_code == 201
    body = res.json()

    assert body["status"] == ApplicationStatus.FAILED.value
    assert body["verification_outcome"] == VerificationOutcome.PERSISTENT_FAILURE.value
    assert "persistent" in body["failure_reason"].lower()

    # Attempting to retry a FAILED application must return 400
    retry_res = client.post(f"/api/v1/applications/{body['id']}/retry")
    assert retry_res.status_code == 400
    assert "cannot be retried" in retry_res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 7. Scenario 7: Business Rule Failure Without Retry
# ---------------------------------------------------------------------------

def test_business_rule_failure_not_retried(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Applications failing business rules transition to REJECTED and cannot be retried."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-biz-reject-01",
        "input_data": {
            "applicant_name": "Low Credit Applicant",
            "credit_score": 500,  # Below threshold of 650
            "simulated_verification": "SUCCESS",
        },
    }

    res = client.post("/api/v1/applications/", json=payload)
    assert res.status_code == 201
    body = res.json()

    assert body["status"] == ApplicationStatus.REJECTED.value
    assert body["decision"]["passed"] is False

    # Attempting to retry a REJECTED application must return 400
    retry_res = client.post(f"/api/v1/applications/{body['id']}/retry")
    assert retry_res.status_code == 400
    assert "cannot be retried" in retry_res.json()["detail"].lower()


# ---------------------------------------------------------------------------
# 8. Scenario 8 & 9: Idempotency & Duplicate Protection
# ---------------------------------------------------------------------------

def test_idempotency_during_retry_lifecycle(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Duplicate submissions during retry lifecycle replay correctly without duplicating audit records."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-idemp-01",
        "input_data": {
            "applicant_name": "Idempotent User",
            "credit_score": 710,
            "simulated_verification": "TEMPORARY_FAILURE",
        },
    }

    # Initial submission
    res1 = client.post("/api/v1/applications/", json=payload)
    assert res1.status_code == 201
    app_id = res1.json()["id"]

    # Re-submission with identical payload -> 200 OK
    res2 = client.post("/api/v1/applications/", json=payload)
    assert res2.status_code == 200
    assert res2.json()["id"] == app_id
    assert res2.json()["status"] == ApplicationStatus.RETRY_PENDING.value

    # Re-submission with differing payload -> 409 Conflict
    conflicting_payload = dict(payload)
    conflicting_payload["input_data"] = {
        "applicant_name": "Different Name",
        "credit_score": 710,
    }
    res_conflict = client.post("/api/v1/applications/", json=conflicting_payload)
    assert res_conflict.status_code == 409

    # Verify audit records not duplicated by replay
    audits = db_session.query(AuditLog).filter_by(application_id=app_id).all()
    assert len(audits) == 1


def test_cannot_retry_approved_application(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Calling retry on an APPROVED application returns 400 Bad Request and does not add audit logs."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-resilience-approved-retry-01",
        "input_data": {
            "applicant_name": "Approved Applicant",
            "credit_score": 750,
            "simulated_verification": "SUCCESS",
        },
    }

    res = client.post("/api/v1/applications/", json=payload)
    app_id = res.json()["id"]
    assert res.json()["status"] == ApplicationStatus.APPROVED.value

    audits_before = db_session.query(AuditLog).filter_by(application_id=app_id).count()

    retry_res = client.post(f"/api/v1/applications/{app_id}/retry")
    assert retry_res.status_code == 400
    assert "cannot be retried" in retry_res.json()["detail"].lower()

    # Re-verify audit log count is unchanged
    audits_after = db_session.query(AuditLog).filter_by(application_id=app_id).count()
    assert audits_before == audits_after


def test_cannot_retry_manual_review_application(
    client: TestClient, db_session: Session, phase4_workflow: str
) -> None:
    """Applications in MANUAL_REVIEW are in terminal review state and cannot be retried via automated API."""
    payload = {
        "workflow_id": phase4_workflow,
        "idempotency_key": "test-manual-review-no-retry-01",
        "input_data": {
            "applicant_name": "Manual Review User",
            "credit_score": 700,
            "simulated_verification": "TEMPORARY_FAILURE",
        },
    }
    # Initial submission + 3 retries (max_retries=3) to reach MANUAL_REVIEW
    res = client.post("/api/v1/applications/", json=payload)
    app_id = res.json()["id"]
    for _ in range(3):
        client.post(f"/api/v1/applications/{app_id}/retry")

    app = db_session.query(Application).filter_by(id=app_id).first()
    assert app.status == ApplicationStatus.MANUAL_REVIEW.value

    # Subsequent retry attempt must return 400
    res_after = client.post(f"/api/v1/applications/{app_id}/retry")
    assert res_after.status_code == 400
    assert "cannot be retried" in res_after.json()["detail"].lower()


def test_zero_max_retries_transitions_directly_to_manual_review(
    client: TestClient, db_session: Session
) -> None:
    """When a workflow config sets max_retries=0, transient failures move directly to MANUAL_REVIEW."""
    create_workflow_config(
        db_session,
        workflow_id="zero_retry_wf",
        version=1,
        config_data={
            "max_retries": 0,
            "rules": [
                {"rule_id": "REQ_X", "category": "mandatory", "field": "x"}
            ],
        },
        is_active=True,
    )

    payload = {
        "workflow_id": "zero_retry_wf",
        "idempotency_key": "test-zero-max-retries-01",
        "input_data": {
            "x": "some_value",
            "simulated_verification": "TEMPORARY_FAILURE",
        },
    }

    res = client.post("/api/v1/applications/", json=payload)
    assert res.status_code == 201
    body = res.json()

    assert body["status"] == ApplicationStatus.MANUAL_REVIEW.value
    assert body["retry_count"] == 0
    assert "0 max_retries" in body["failure_reason"]


# ---------------------------------------------------------------------------
# 9. Scenario 10 & 11: Invalid States & Non-Existent Applications
# ---------------------------------------------------------------------------

def test_retry_non_existent_application(client: TestClient) -> None:
    """Retrying a non-existent application returns 404 Not Found."""
    res = client.post("/api/v1/applications/999999/retry")
    assert res.status_code == 404
    assert "not found" in res.json()["detail"].lower()


def test_orchestrator_raises_on_invalid_state_retry(db_session: Session, phase4_workflow: str) -> None:
    """Direct orchestrator call raises IneligibleRetryError for invalid application states."""
    req = ApplicationCreateRequest(
        workflow_id=phase4_workflow,
        idempotency_key="direct-state-test",
        input_data={"applicant_name": "Direct Test", "credit_score": 700},
    )
    result = orchestrator.process_application(db_session, req)
    app = result.application

    # Manually test error directly
    with pytest.raises(IneligibleRetryError):
        orchestrator.retry_application(db_session, app.id)


# ---------------------------------------------------------------------------
# 10. Scenario 12: Atomic Persistence and External Simulator Independence
# ---------------------------------------------------------------------------

def test_retry_atomic_persistence_rollback_on_db_error(
    db_session: Session, phase4_workflow: str
) -> None:
    """Database failure during retry commits rolls back cleanly without leaving partial state."""
    req = ApplicationCreateRequest(
        workflow_id=phase4_workflow,
        idempotency_key="atomic-retry-test-01",
        input_data={
            "applicant_name": "Rollback Test",
            "credit_score": 700,
            "simulated_verification": "TEMPORARY_FAILURE",
        },
    )
    result = orchestrator.process_application(db_session, req)
    app_id = result.application.id

    initial_app = db_session.query(Application).filter_by(id=app_id).first()
    assert initial_app.status == ApplicationStatus.RETRY_PENDING.value
    assert initial_app.retry_count == 0

    # Simulate an unhandled database commit exception during retry
    with patch.object(db_session, "commit", side_effect=RuntimeError("Simulated DB Connection Failure")):
        with pytest.raises(RuntimeError, match="Simulated DB Connection Failure"):
            orchestrator.retry_application(db_session, app_id)

    # Re-query application in a fresh state to verify rollback
    db_session.expire_all()
    rolled_back_app = db_session.query(Application).filter_by(id=app_id).first()
    assert rolled_back_app.status == ApplicationStatus.RETRY_PENDING.value
    assert rolled_back_app.retry_count == 0

    # Only initial audit log exists
    audit_count = db_session.query(AuditLog).filter_by(application_id=app_id).count()
    assert audit_count == 1
