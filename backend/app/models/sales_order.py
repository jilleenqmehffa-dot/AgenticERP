from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import SalesOrderStatus
from app.db.base import Base


class SalesOrder(Base):
    __tablename__ = "sales_orders"
    __table_args__ = (
        CheckConstraint("total_amount >= 0", name="ck_sales_orders_total_amount_nonnegative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[SalesOrderStatus] = mapped_column(
        Enum(
            SalesOrderStatus,
            name="sales_order_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=SalesOrderStatus.DRAFT,
        server_default=SalesOrderStatus.DRAFT.value,
    )
    total_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0.00"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
