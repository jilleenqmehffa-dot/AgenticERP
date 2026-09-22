from datetime import datetime
from typing import Any, TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import SubmissionStatus
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business_task import BusinessTask
    from app.models.task_execution import TaskExecution


class TaskSubmission(Base):
    __tablename__ = "task_submissions"
    __table_args__ = (
        UniqueConstraint("task_id", "version", name="uq_task_submissions_task_version"),
        UniqueConstraint("task_id", "payload_hash", name="uq_task_submissions_task_payload"),
        Index("ix_task_submissions_task_status", "task_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[SubmissionStatus] = mapped_column(
        Enum(SubmissionStatus, name="submission_status", native_enum=False,
             create_constraint=True, validate_strings=True),
        default=SubmissionStatus.PENDING_REVIEW,
        server_default=SubmissionStatus.PENDING_REVIEW.value,
    )
    form_data: Mapped[dict[str, Any]] = mapped_column("payload", JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    submitted_by_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), index=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped["BusinessTask"] = relationship(back_populates="submissions")
    submitter = relationship("Employee", foreign_keys=[submitted_by_id])
    reviewer = relationship("Employee", foreign_keys=[reviewed_by_id])
    executions: Mapped[list["TaskExecution"]] = relationship(back_populates="submission")
