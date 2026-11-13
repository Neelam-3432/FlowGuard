"""Tests for health check and documentation endpoints."""

from fastapi.testclient import TestClient


def test_health_check_root(client: TestClient) -> None:
    """Verify that GET /health returns HTTP 200 with the expected payload."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app_name"] == "FlowGuard"
    assert "version" in data


def test_health_check_api_v1(client: TestClient) -> None:
    """Verify that GET /api/v1/health returns HTTP 200 with the expected payload."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["app_name"] == "FlowGuard"


def test_swagger_docs_accessible(client: TestClient) -> None:
    """Verify that Swagger UI documentation is accessible at /docs."""
    response = client.get("/docs")
    assert response.status_code == 200
    assert "swagger-ui" in response.text.lower() or "html" in response.text.lower()


def test_openapi_schema_accessible(client: TestClient) -> None:
    """Verify that OpenAPI JSON schema is accessible at /openapi.json."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    data = response.json()
    assert data["info"]["title"] == "FlowGuard"
    assert "/health" in data["paths"]

