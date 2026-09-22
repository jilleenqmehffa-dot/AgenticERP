from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Computed, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business_task import BusinessTask


class InventoryCountItem(Base):
    __tablename__ = "inventory_count_items"
    __table_args__ = (
        CheckConstraint(
            "system_quantity >= 0",
            name="ck_inventory_count_items_system_quantity_nonnegative",
        ),
        CheckConstraint(
            "counted_quantity IS NULL OR counted_quantity >= 0",
            name="ck_inventory_count_items_counted_quantity_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    location_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="RESTRICT"), index=True
    )
    system_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    counted_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3), nullable=True
    )
    difference_quantity: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 3),
        Computed("counted_quantity - system_quantity", persisted=True),
        nullable=True,
    )

    task: Mapped["BusinessTask"] = relationship(
        back_populates="inventory_count_items"
    )
