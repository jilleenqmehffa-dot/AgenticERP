from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AdjustmentStatus
from app.db.base import Base


class InventoryAdjustment(Base):
    __tablename__ = "inventory_adjustments"
    __table_args__ = (
        CheckConstraint("difference_quantity <> 0", name="ck_inventory_adjustments_nonzero"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    count_item_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_count_items.id", ondelete="RESTRICT"), unique=True, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="RESTRICT"))
    warehouse_code: Mapped[str] = mapped_column(String(64))
    location_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="RESTRICT")
    )
    system_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    difference_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    status: Mapped[AdjustmentStatus] = mapped_column(
        Enum(AdjustmentStatus, name="adjustment_status", native_enum=False,
             create_constraint=True, validate_strings=True),
        default=AdjustmentStatus.PENDING_REVIEW,
        server_default=AdjustmentStatus.PENDING_REVIEW.value,
    )
    reviewed_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), nullable=True
    )
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    adjustment_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="RESTRICT"), unique=True, nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
