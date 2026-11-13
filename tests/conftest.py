"""Pytest fixtures for FlowGuard test suite."""

from typing import Generator
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    """Yield a TestClient instance for sending API requests during tests."""
    with TestClient(app) as test_client:
        yield test_client

