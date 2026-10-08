from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ActorType, RecommendationStatus, RecommendationType, TaskType
from app.db.base import Base


class TaskRecommendation(Base):
    __tablename__ = "task_recommendations"
    __table_args__ = (
        CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_task_recommendations_source_complete",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_task_recommendations_confidence_range",
        ),
        Index("ix_task_recommendations_source", "source_type", "source_id"),
        UniqueConstraint("approved_task_id", name="uq_task_recommendations_approved_task"),
        UniqueConstraint(
            "approved_reservation_id",
            name="uq_task_recommendations_approved_reservation",
        ),
        CheckConstraint(
            "(recommendation_type = 'TASK' AND task_type IS NOT NULL) OR "
            "(recommendation_type = 'RESERVATION' AND task_type IS NULL "
            "AND source_type = 'OUTBOUND_ORDER_ITEM' AND source_id IS NOT NULL)",
            name="ck_task_recommendations_type_source",
        ),
        CheckConstraint(
            "recommendation_type != 'RESERVATION' OR status != 'APPROVED' "
            "OR approved_reservation_id IS NOT NULL",
            name="ck_task_recommendations_reservation_approval_complete",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    recommendation_type: Mapped[RecommendationType] = mapped_column(
        Enum(
            RecommendationType,
            name="recommendation_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=RecommendationType.TASK,
        server_default=RecommendationType.TASK.value,
    )
    task_type: Mapped[TaskType | None] = mapped_column(
        Enum(TaskType, name="recommendation_task_type", native_enum=False,
             create_constraint=True, validate_strings=True),
        nullable=True,
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"), index=True
    )
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    proposed_assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    rationale: Mapped[str] = mapped_column(Text)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    proposed_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(RecommendationStatus, name="recommendation_status", native_enum=False,
             create_constraint=True, validate_strings=True),
        default=RecommendationStatus.SUGGESTED,
        server_default=RecommendationStatus.SUGGESTED.value,
    )
    suggested_by_type: Mapped[ActorType] = mapped_column(
        Enum(ActorType, name="recommendation_actor_type", native_enum=False,
             create_constraint=True, validate_strings=True)
    )
    suggested_by_id: Mapped[str] = mapped_column(String(255))
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="SET NULL"), nullable=True
    )
    approved_reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_reservations.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    approved_task = relationship("BusinessTask", foreign_keys=[approved_task_id])
    approved_reservation = relationship(
        "StockReservation", foreign_keys=[approved_reservation_id]
    )
    proposed_assignee = relationship("Employee", foreign_keys=[proposed_assignee_id])
    reviewer = relationship("Employee", foreign_keys=[reviewed_by_id])
