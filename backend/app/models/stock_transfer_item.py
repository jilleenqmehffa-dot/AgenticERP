from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockTransferItem(Base):
    __tablename__ = "stock_transfer_items"
    __table_args__ = (
        CheckConstraint("planned_quantity > 0", name="ck_transfer_items_planned_positive"),
        CheckConstraint(
            "shipped_quantity >= 0 AND shipped_quantity <= planned_quantity",
            name="ck_transfer_items_shipped_valid",
        ),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= shipped_quantity",
            name="ck_transfer_items_received_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_transfer_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transfers.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    shipped_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
