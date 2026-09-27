from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.enums import StockStatus

if TYPE_CHECKING:
    from app.models.business_task import BusinessTask
    from app.models.inventory_bucket import InventoryBucket
    from app.models.warehouse_location import WarehouseLocation


class BusinessTaskItem(Base):
    __tablename__ = "business_task_items"
    __table_args__ = (
        CheckConstraint(
            "planned_quantity > 0",
            name="ck_business_task_items_planned_quantity_positive",
        ),
        CheckConstraint(
            "actual_quantity IS NULL OR actual_quantity >= 0",
            name="ck_business_task_items_actual_quantity_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    source_bucket_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_buckets.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    target_stock_status: Mapped[StockStatus | None] = mapped_column(
        Enum(
            StockStatus,
            name="business_task_target_stock_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    actual_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )

    task: Mapped["BusinessTask"] = relationship(back_populates="items")
    source_bucket: Mapped["InventoryBucket | None"] = relationship()
    from_location: Mapped["WarehouseLocation | None"] = relationship(
        foreign_keys=[from_location_id]
    )
    to_location: Mapped["WarehouseLocation | None"] = relationship(
        foreign_keys=[to_location_id]
    )
