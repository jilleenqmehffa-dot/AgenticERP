from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ReceivableStatus
from app.db.base import Base


class AccountReceivable(Base):
    __tablename__ = "account_receivables"
    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="ck_account_receivables_amount_nonnegative",
        ),
        CheckConstraint(
            "paid_amount >= 0",
            name="ck_account_receivables_paid_amount_nonnegative",
        ),
        CheckConstraint(
            "paid_amount <= amount",
            name="ck_account_receivables_paid_not_above_amount",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sales_order_id: Mapped[int] = mapped_column(
        ForeignKey("sales_orders.id"),
        unique=True,
        index=True,
    )
    customer_name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        server_default="0",
    )
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[ReceivableStatus] = mapped_column(
        Enum(
            ReceivableStatus,
            name="receivable_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ReceivableStatus.UNPAID,
        server_default=ReceivableStatus.UNPAID.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    sales_order: Mapped["SalesOrder"] = relationship(back_populates="receivable")

    @hybrid_property
    def outstanding_amount(self) -> Decimal:
        return self.amount - self.paid_amount
