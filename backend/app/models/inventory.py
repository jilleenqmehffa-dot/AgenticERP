from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import InventoryStatus
from app.db.base import Base


class Inventory(Base):
    __tablename__ = "inventories"
    __table_args__ = (
        CheckConstraint(
            "on_hand_quantity >= 0",
            name="ck_inventories_on_hand_quantity_nonnegative",
        ),
        CheckConstraint(
            "reserved_quantity >= 0",
            name="ck_inventories_reserved_quantity_nonnegative",
        ),
        CheckConstraint(
            "reserved_quantity <= on_hand_quantity",
            name="ck_inventories_reserved_not_above_on_hand",
        ),
        CheckConstraint(
            "low_stock_threshold >= 0",
            name="ck_inventories_low_stock_threshold_nonnegative",
        ),
        UniqueConstraint(
            "product_id",
            "warehouse_code",
            name="uq_inventories_product_warehouse",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    on_hand_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3),
        default=Decimal("0.000"),
        server_default="0",
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3),
        default=Decimal("0.000"),
        server_default="0",
    )
    status: Mapped[InventoryStatus] = mapped_column(
        Enum(
            InventoryStatus,
            name="inventory_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=InventoryStatus.OUT_OF_STOCK,
        server_default=InventoryStatus.OUT_OF_STOCK.value,
    )
    low_stock_threshold: Mapped[Decimal] = mapped_column(
        Numeric(18, 3),
        default=Decimal("0.000"),
        server_default="0",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    product: Mapped["Product"] = relationship(back_populates="inventories")

    @hybrid_property
    def available_quantity(self) -> Decimal:
        return self.on_hand_quantity - self.reserved_quantity
