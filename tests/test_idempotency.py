"""Tests for idempotency guarantees, replays, and conflict handling."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models.application import Application
from app.models.audit_log import AuditLog
from app.services.workflow_config_service import create_workflow_config


def setup_idempotency_workflow(db_session: Session) -> None:
    """Helper to set up workflow configuration."""
    create_workflow_config(
        db_session,
        workflow_id="idemp_workflow",
        version=1,
        config_data={
            "rules": [
                {"rule_id": "REQ_USER", "category": "mandatory", "field": "user_id"}
            ]
        },
        is_active=True,
    )


def test_idempotent_replay_identical_payload(client: TestClient, db_session: Session) -> None:
    """Verify that submitting the same idempotency_key with identical payload returns 200 OK without duplicate DB rows."""
    setup_idempotency_workflow(db_session)

    payload = {
        "workflow_id": "idemp_workflow",
        "idempotency_key": "idemp-key-repeat-01",
        "input_data": {"user_id": "user_12345"},
    }

    # First submission: 201 Created
    res1 = client.post("/api/v1/applications/", json=payload)
    assert res1.status_code == 201
    data1 = res1.json()
    app_id = data1["id"]

    # Second submission: 200 OK (idempotent replay)
    res2 = client.post("/api/v1/applications/", json=payload)
    assert res2.status_code == 200
    data2 = res2.json()

    # Must refer to the exact same application
    assert data2["id"] == app_id
    assert data2["request_id"] == data1["request_id"]
    assert data2["status"] == data1["status"]

    # Verify database has exactly 1 application record
    count = db_session.query(Application).filter_by(
        workflow_id="idemp_workflow",
        idempotency_key="idemp-key-repeat-01"
    ).count()
    assert count == 1


def test_idempotency_no_duplicate_audit_records(client: TestClient, db_session: Session) -> None:
    """Verify that multiple replays do not write duplicate audit logs."""
    setup_idempotency_workflow(db_session)

    payload = {
        "workflow_id": "idemp_workflow",
        "idempotency_key": "idemp-key-no-audit-dup",
        "input_data": {"user_id": "user_54321"},
    }

    # Submit 3 times
    for _ in range(3):
        res = client.post("/api/v1/applications/", json=payload)
        assert res.status_code in (200, 201)

    # Count audit logs for this application
    app = db_session.query(Application).filter_by(
        workflow_id="idemp_workflow",
        idempotency_key="idemp-key-no-audit-dup"
    ).first()
    assert app is not None

    audit_count = db_session.query(AuditLog).filter_by(application_id=app.id).count()
    assert audit_count == 1, "Idempotent replays must not create duplicate audit logs"


def test_idempotency_conflict_different_payload(client: TestClient, db_session: Session) -> None:
    """Verify that reusing an idempotency key with different input data returns 409 Conflict."""
    setup_idempotency_workflow(db_session)

    payload1 = {
        "workflow_id": "idemp_workflow",
        "idempotency_key": "idemp-key-conflict-01",
        "input_data": {"user_id": "user_initial", "amount": 100},
    }

    res1 = client.post("/api/v1/applications/", json=payload1)
    assert res1.status_code == 201

    # Second submission with same key but different payload
    payload2 = {
        "workflow_id": "idemp_workflow",
        "idempotency_key": "idemp-key-conflict-01",
        "input_data": {"user_id": "user_different", "amount": 999},
    }

    res2 = client.post("/api/v1/applications/", json=payload2)
    assert res2.status_code == 409
    data2 = res2.json()
    assert "different submission data" in data2["detail"]

