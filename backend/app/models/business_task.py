from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ActorType, TaskStatus, TaskType
from app.db.base import Base


class BusinessTask(Base):
    __tablename__ = "business_tasks"
    __table_args__ = (
        CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_business_tasks_source_complete",
        ),
        Index(
            "ix_business_tasks_source",
            "source_type",
            "source_id",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    task_type: Mapped[TaskType] = mapped_column(
        Enum(
            TaskType,
            name="task_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(
            TaskStatus,
            name="task_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=TaskStatus.PENDING,
        server_default=TaskStatus.PENDING.value,
    )
    assigned_employee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    planned_data: Mapped[dict[str, Any]] = mapped_column(JSONB)
    actual_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    exception_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by_type: Mapped[ActorType] = mapped_column(
        Enum(
            ActorType,
            name="business_task_actor_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    created_by_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    assigned_employee: Mapped["Employee"] = relationship(
        back_populates="assigned_tasks"
    )
