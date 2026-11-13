"""Pytest fixtures for FlowGuard test suite."""

from pathlib import Path
from typing import Generator
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.core.database import Base, get_db
from app.main import app

# Ensure testing flag is active
settings.testing = True


@pytest.fixture(scope="session", autouse=True)
def guard_dev_database() -> Generator[None, None, None]:
    """Ensure the development database flowguard.db is not created or modified by tests."""
    dev_db = Path("flowguard.db")
    originally_existed = dev_db.exists()

    yield

    # If flowguard.db was created during the test run, fail the test run
    if not originally_existed and dev_db.exists():
        dev_db.unlink(missing_ok=True)
        raise AssertionError("Tests created 'flowguard.db' in the project root! Tests must use isolated databases.")


@pytest.fixture(scope="function")
def test_engine(tmp_path: Path) -> Generator[Engine, None, None]:
    """Create an isolated, temporary SQLite database engine for testing."""
    test_db_path = tmp_path / "test_flowguard.db"
    test_db_url = f"sqlite:///{test_db_path}"

    engine = create_engine(
        test_db_url,
        connect_args={"check_same_thread": False},
    )

    # Explicitly enforce foreign key constraints on the test SQLite engine
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables in the temporary database
    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(test_engine: Engine) -> Generator[Session, None, None]:
    """Yield an isolated database session bound to the temporary test database."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(scope="function")
def client(db_session: Session) -> Generator[TestClient, None, None]:
    """Yield a TestClient configured with get_db dependency overridden to use the test session."""
    def override_get_db() -> Generator[Session, None, None]:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
