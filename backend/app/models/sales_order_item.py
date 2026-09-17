from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_sales_order_items_quantity_positive"),
        CheckConstraint("unit_price >= 0", name="ck_sales_order_items_unit_price_nonnegative"),
        CheckConstraint("amount >= 0", name="ck_sales_order_items_amount_nonnegative"),
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

    sales_order: Mapped["SalesOrder"] = relationship(back_populates="items")
    product: Mapped["Product"] = relationship(back_populates="sales_order_items")
