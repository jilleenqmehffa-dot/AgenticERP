from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class OutboundOrderItem(Base):
    __tablename__ = "outbound_order_items"
    __table_args__ = (
        CheckConstraint("requested_quantity > 0", name="ck_outbound_items_requested_positive"),
        CheckConstraint(
            "reserved_quantity >= 0 AND reserved_quantity <= requested_quantity",
            name="ck_outbound_items_reserved_valid",
        ),
        CheckConstraint(
            "picked_quantity >= 0 AND picked_quantity <= reserved_quantity",
            name="ck_outbound_items_picked_valid",
        ),
        CheckConstraint(
            "shipped_quantity >= 0 AND shipped_quantity <= picked_quantity",
            name="ck_outbound_items_shipped_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    outbound_order_id: Mapped[int] = mapped_column(
        ForeignKey("outbound_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    requested_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    picked_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    shipped_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
