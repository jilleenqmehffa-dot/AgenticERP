from datetime import datetime
from typing import TYPE_CHECKING

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ActorType, TaskStatus, TaskType
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business_task_item import BusinessTaskItem
    from app.models.employee import Employee
    from app.models.inventory_count_item import InventoryCountItem
    from app.models.task_execution import TaskExecution
    from app.models.task_submission import TaskSubmission
    from app.models.warehouse import Warehouse


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
        default=TaskStatus.ASSIGNED,
        server_default=TaskStatus.ASSIGNED.value,
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    assignee_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    failed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    warehouse: Mapped["Warehouse"] = relationship(back_populates="tasks")
    assignee: Mapped["Employee"] = relationship(
        back_populates="assigned_tasks"
    )
    items: Mapped[list["BusinessTaskItem"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )
    inventory_count_items: Mapped[list["InventoryCountItem"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )
    submissions: Mapped[list["TaskSubmission"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )
    executions: Mapped[list["TaskExecution"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
    )
