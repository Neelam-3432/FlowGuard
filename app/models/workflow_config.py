"""SQLAlchemy model for Workflow Configuration versions."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List
from sqlalchemy import Boolean, DateTime, Index, Integer, JSON, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.orm.attributes import get_history
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.application import Application


class WorkflowConfig(Base):
    """Workflow configuration version model.

    Stores versioned configurations for decision workflows. Historical versions
    are immutable to ensure auditability and decision reproducibility.
    """

    __tablename__ = "workflow_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workflow_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    applications: Mapped[List["Application"]] = relationship(
        "Application",
        back_populates="workflow_config",
        cascade="none",
    )

    __table_args__ = (
        UniqueConstraint("workflow_id", "version", name="uq_workflow_config_workflow_version"),
        Index("ix_workflow_configs_workflow_active", "workflow_id", "is_active"),
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowConfig(id={self.id}, workflow_id='{self.workflow_id}', "
            f"version={self.version}, is_active={self.is_active})>"
        )


@event.listens_for(WorkflowConfig, "before_update")
def enforce_workflow_config_immutability(mapper: Any, connection: Any, target: WorkflowConfig) -> None:
    """Enforce immutability of historical workflow configuration versions.

    Prevents modifying workflow_id, version, or config_data once saved.
    Only the active status (is_active) can be modified.
    """
    config_hist = get_history(target, "config_data")
    if config_hist.has_changes():
        raise ValueError(
            f"WorkflowConfig {target.id} (workflow '{target.workflow_id}', v{target.version}) is immutable. "
            "Configuration data cannot be modified. Create a new version instead."
        )

    version_hist = get_history(target, "version")
    if version_hist.has_changes():
        raise ValueError("Cannot modify version number of an existing workflow configuration.")

    workflow_id_hist = get_history(target, "workflow_id")
    if workflow_id_hist.has_changes():
        raise ValueError("Cannot modify workflow_id of an existing workflow configuration.")

