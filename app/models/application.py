"""SQLAlchemy model for Applications."""

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, List
from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

if TYPE_CHECKING:
    from app.models.workflow_config import WorkflowConfig
    from app.models.audit_log import AuditLog


class Application(Base):
    """Application entity representing an incoming decision workflow request."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    workflow_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    workflow_config_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("workflow_configs.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    input_data: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="PENDING", index=True)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    # Relationships
    workflow_config: Mapped["WorkflowConfig"] = relationship(
        "WorkflowConfig",
        back_populates="applications",
    )
    audit_logs: Mapped[List["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="AuditLog.created_at.asc()",
    )

    __table_args__ = (
        UniqueConstraint("workflow_id", "idempotency_key", name="uq_application_workflow_idempotency"),
        Index("ix_applications_workflow_status", "workflow_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<Application(id={self.id}, request_id='{self.request_id}', "
            f"workflow_id='{self.workflow_id}', status='{self.status}')>"
        )

