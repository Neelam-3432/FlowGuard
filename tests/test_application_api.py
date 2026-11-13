"""API tests for application submission and processing endpoint."""

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.services.workflow_config_service import create_workflow_config


def setup_sample_workflow(db_session: Session) -> None:
    """Helper to set up a sample workflow in the test database."""
    config_data = {
        "version": "1.0",
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
    }
    create_workflow_config(
        db_session,
        workflow_id="credit_check",
        version=1,
        config_data=config_data,
        is_active=True,
    )


def test_api_submit_application_approved(client: TestClient, db_session: Session) -> None:
    """Verify POST /api/v1/applications/ returns 201 Created with status APPROVED on valid payload."""
    setup_sample_workflow(db_session)

    payload = {
        "workflow_id": "credit_check",
        "idempotency_key": "api-test-key-001",
        "input_data": {
            "applicant_name": "Eleanor Vance",
            "credit_score": 720,
        },
    }

    response = client.post("/api/v1/applications/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["id"] is not None
    assert data["workflow_id"] == "credit_check"
    assert data["status"] == "APPROVED"
    assert data["decision"] is not None
    assert data["decision"]["passed"] is True
    assert data["decision"]["status"] == "approved"
    assert data["decision"]["passed_rules"] == 2


def test_api_submit_application_rejected(client: TestClient, db_session: Session) -> None:
    """Verify POST /api/v1/applications/ returns 201 Created with status REJECTED on failing rules."""
    setup_sample_workflow(db_session)

    payload = {
        "workflow_id": "credit_check",
        "idempotency_key": "api-test-key-002",
        "input_data": {
            "applicant_name": "Frank",
            "credit_score": 600,  # Below threshold 650
        },
    }

    response = client.post("/api/v1/applications/", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "REJECTED"
    assert data["decision"]["passed"] is False
    assert data["decision"]["failed_rules"] == 1


def test_api_submit_missing_required_fields(client: TestClient) -> None:
    """Verify submitting payload missing required properties returns 422 Unprocessable Entity."""
    # Missing input_data
    res1 = client.post("/api/v1/applications/", json={"workflow_id": "credit_check", "idempotency_key": "k1"})
    assert res1.status_code == 422

    # Missing workflow_id
    res2 = client.post("/api/v1/applications/", json={"idempotency_key": "k2", "input_data": {}})
    assert res2.status_code == 422

    # Missing idempotency_key
    res3 = client.post("/api/v1/applications/", json={"workflow_id": "credit_check", "input_data": {}})
    assert res3.status_code == 422


def test_api_submit_unknown_workflow(client: TestClient) -> None:
    """Verify submitting to a non-existent workflow returns 404 Not Found."""
    payload = {
        "workflow_id": "non_existent_wf",
        "idempotency_key": "unknown-wf-key",
        "input_data": {"test": 123},
    }

    response = client.post("/api/v1/applications/", json=payload)
    assert response.status_code == 404
    data = response.json()
    assert "not found" in data["detail"].lower()


def test_api_submit_invalid_workflow_config(client: TestClient, db_session: Session) -> None:
    """Verify that a corrupted or malformed configuration in database returns 500 Internal Server Error."""
    create_workflow_config(
        db_session,
        workflow_id="corrupted_wf",
        version=1,
        config_data={"rules": [{"rule_id": "BAD", "category": "unknown_cat"}]},
        is_active=True,
    )

    payload = {
        "workflow_id": "corrupted_wf",
        "idempotency_key": "corrupted-wf-key",
        "input_data": {"val": 1},
    }

    response = client.post("/api/v1/applications/", json=payload)
    assert response.status_code == 500
    assert "invalid" in response.json()["detail"].lower()


def test_api_route_without_trailing_slash(client: TestClient, db_session: Session) -> None:
    """Verify that route handles URLs without trailing slash cleanly."""
    setup_sample_workflow(db_session)

    payload = {
        "workflow_id": "credit_check",
        "idempotency_key": "no-slash-key",
        "input_data": {"applicant_name": "Grace", "credit_score": 750},
    }

    response = client.post("/api/v1/applications", json=payload)
    assert response.status_code in (200, 201)

