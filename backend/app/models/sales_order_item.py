from decimal import Decimal

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.enums import OrderItemStatus


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sales_order_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_sales_order_items_unit_price_nonnegative"),
        CheckConstraint("amount >= 0", name="ck_sales_order_items_amount_nonnegative"),
        CheckConstraint(
            "reserved_quantity >= 0 AND reserved_quantity <= quantity",
            name="ck_sales_order_items_reserved_quantity_valid",
        ),
        CheckConstraint(
            "picked_quantity >= 0 AND picked_quantity <= reserved_quantity",
            name="ck_sales_order_items_picked_quantity_valid",
        ),
        CheckConstraint(
            "shipped_quantity >= 0 AND shipped_quantity <= picked_quantity",
            name="ck_sales_order_items_shipped_quantity_valid",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="CASCADE"),
        index=True,
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id"),
        index=True,
    )
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    unit_price: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[OrderItemStatus] = mapped_column(
        Enum(
            OrderItemStatus,
            name="order_item_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=OrderItemStatus.PENDING,
        server_default=OrderItemStatus.PENDING.value,
    )
    reserved_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    picked_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    shipped_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )

    sales_order: Mapped["SalesOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="sales_order_items")
