from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ExecutionStatus
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business_task import BusinessTask
    from app.models.task_submission import TaskSubmission


class TaskExecution(Base):
    __tablename__ = "task_executions"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="ck_task_executions_attempt_nonnegative"),
        UniqueConstraint(
            "task_id", "submission_id", "capability_name",
            name="uq_task_executions_task_submission_capability",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("task_submissions.id", ondelete="RESTRICT"), index=True
    )
    capability_name: Mapped[str] = mapped_column(String(100))
    idempotency_key: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus, name="execution_status", native_enum=False,
             create_constraint=True, validate_strings=True),
        default=ExecutionStatus.PENDING,
        server_default=ExecutionStatus.PENDING.value,
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    task: Mapped["BusinessTask"] = relationship(back_populates="executions")
    submission: Mapped["TaskSubmission"] = relationship(back_populates="executions")
