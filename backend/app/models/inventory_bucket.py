from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import StockStatus
from app.db.base import Base


class InventoryBucket(Base):
    __tablename__ = "inventory_buckets"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="ck_inventory_buckets_quantity_nonnegative"),
        UniqueConstraint(
            "product_id",
            "warehouse_code",
            "location_code",
            "lot_no",
            "stock_status",
            name="uq_inventory_buckets_identity",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    location_code: Mapped[str] = mapped_column(String(64), default="", server_default="")
    lot_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    stock_status: Mapped[StockStatus] = mapped_column(
        Enum(
            StockStatus,
            name="stock_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
