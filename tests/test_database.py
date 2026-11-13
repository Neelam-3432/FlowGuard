"""Tests for database engine, initialization, and SQLite configuration."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from app.core.database import Base


def test_database_initialization_tables_created(test_engine: Engine) -> None:
    """Verify that all expected tables are created during database initialization."""
    inspector = inspect(test_engine)
    table_names = inspector.get_table_names()

    assert "workflow_configs" in table_names
    assert "applications" in table_names
    assert "audit_logs" in table_names


def test_sqlite_foreign_keys_pragma_enabled(db_session: Session) -> None:
    """Verify that SQLite foreign key constraint enforcement is enabled."""
    result = db_session.execute(text("PRAGMA foreign_keys")).scalar()
    assert result == 1, "SQLite foreign_keys PRAGMA must be 1 (enabled)."


def test_table_columns_and_primary_keys(test_engine: Engine) -> None:
    """Verify that table schemas have correct columns and primary keys."""
    inspector = inspect(test_engine)

    # WorkflowConfig table check
    config_cols = {col["name"] for col in inspector.get_columns("workflow_configs")}
    expected_config_cols = {"id", "workflow_id", "version", "config_data", "is_active", "created_at"}
    assert expected_config_cols.issubset(config_cols)
    assert inspector.get_pk_constraint("workflow_configs")["constrained_columns"] == ["id"]

    # Applications table check
    app_cols = {col["name"] for col in inspector.get_columns("applications")}
    expected_app_cols = {
        "id", "request_id", "workflow_id", "workflow_config_id",
        "idempotency_key", "payload_hash", "input_data", "status",
        "retry_count", "created_at", "updated_at"
    }
    assert expected_app_cols.issubset(app_cols)
    assert inspector.get_pk_constraint("applications")["constrained_columns"] == ["id"]

    # AuditLogs table check
    audit_cols = {col["name"] for col in inspector.get_columns("audit_logs")}
    expected_audit_cols = {
        "id", "application_id", "event_type", "previous_state",
        "new_state", "details", "created_at"
    }
    assert expected_audit_cols.issubset(audit_cols)
    assert inspector.get_pk_constraint("audit_logs")["constrained_columns"] == ["id"]

