"""Workflow configuration service managing versioned workflow configs."""

from typing import Any, List, Optional
from sqlalchemy.orm import Session
from app.models.workflow_config import WorkflowConfig


def create_workflow_config(
    db: Session,
    *,
    workflow_id: str,
    version: int,
    config_data: dict[str, Any],
    is_active: bool = True,
) -> WorkflowConfig:
    """Create a new versioned workflow configuration.

    Historical configuration versions are immutable. If a configuration with
    the specified workflow_id and version already exists, a ValueError is raised.
    """
    existing = (
        db.query(WorkflowConfig)
        .filter(
            WorkflowConfig.workflow_id == workflow_id,
            WorkflowConfig.version == version,
        )
        .first()
    )
    if existing:
        raise ValueError(
            f"WorkflowConfig for workflow '{workflow_id}' version {version} already exists. "
            "Versions are immutable and cannot be overwritten."
        )

    config = WorkflowConfig(
        workflow_id=workflow_id,
        version=version,
        config_data=config_data,
        is_active=is_active,
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def create_next_workflow_version(
    db: Session,
    *,
    workflow_id: str,
    config_data: dict[str, Any],
    set_active: bool = True,
) -> WorkflowConfig:
    """Create the next sequential version of a workflow configuration.

    Finds the highest current version for the workflow and increments it by 1.
    If set_active is True, all previous versions for this workflow are deactivated.
    """
    latest = (
        db.query(WorkflowConfig)
        .filter(WorkflowConfig.workflow_id == workflow_id)
        .order_by(WorkflowConfig.version.desc())
        .first()
    )
    next_version = (latest.version + 1) if latest else 1

    if set_active:
        # Deactivate previous active configurations
        db.query(WorkflowConfig).filter(
            WorkflowConfig.workflow_id == workflow_id,
            WorkflowConfig.is_active.is_(True),
        ).update({"is_active": False}, synchronize_session=False)

    new_config = WorkflowConfig(
        workflow_id=workflow_id,
        version=next_version,
        config_data=config_data,
        is_active=set_active,
    )
    db.add(new_config)
    db.commit()
    db.refresh(new_config)
    return new_config


def get_active_workflow_config(
    db: Session,
    workflow_id: str,
) -> Optional[WorkflowConfig]:
    """Retrieve the currently active configuration for a workflow."""
    return (
        db.query(WorkflowConfig)
        .filter(
            WorkflowConfig.workflow_id == workflow_id,
            WorkflowConfig.is_active.is_(True),
        )
        .order_by(WorkflowConfig.version.desc())
        .first()
    )


def get_workflow_config_by_version(
    db: Session,
    workflow_id: str,
    version: int,
) -> Optional[WorkflowConfig]:
    """Retrieve a specific version of a workflow configuration."""
    return (
        db.query(WorkflowConfig)
        .filter(
            WorkflowConfig.workflow_id == workflow_id,
            WorkflowConfig.version == version,
        )
        .first()
    )


def deactivate_workflow_config(
    db: Session,
    config_id: int,
) -> WorkflowConfig:
    """Deactivate a workflow configuration without modifying its configuration data."""
    config = db.query(WorkflowConfig).filter(WorkflowConfig.id == config_id).first()
    if not config:
        raise ValueError(f"WorkflowConfig with ID {config_id} not found.")

    config.is_active = False
    db.commit()
    db.refresh(config)
    return config

