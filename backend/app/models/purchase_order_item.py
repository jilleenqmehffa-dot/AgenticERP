from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PurchaseOrderItem(Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        CheckConstraint("ordered_quantity > 0", name="ck_purchase_items_ordered_positive"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= ordered_quantity",
            name="ck_purchase_items_received_valid",
        ),
        CheckConstraint(
            "accepted_quantity >= 0 AND rejected_quantity >= 0",
            name="ck_purchase_items_disposition_nonnegative",
        ),
        CheckConstraint(
            "accepted_quantity + rejected_quantity <= received_quantity",
            name="ck_purchase_items_disposition_within_received",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    ordered_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    accepted_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
