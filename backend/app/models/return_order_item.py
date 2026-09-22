from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReturnOrderItem(Base):
    __tablename__ = "return_order_items"
    __table_args__ = (
        CheckConstraint("requested_quantity > 0", name="ck_return_items_requested_positive"),
        CheckConstraint(
            "shipped_quantity >= 0 AND shipped_quantity <= requested_quantity",
            name="ck_return_items_shipped_valid",
        ),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= shipped_quantity",
            name="ck_return_items_received_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    return_order_id: Mapped[int] = mapped_column(
        ForeignKey("return_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    shipped_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
