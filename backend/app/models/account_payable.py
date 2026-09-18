from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, DateTime, Enum, Numeric, String, func
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import PayableStatus
from app.db.base import Base


class AccountPayable(Base):
    __tablename__ = "account_payables"
    __table_args__ = (
        CheckConstraint(
            "amount >= 0",
            name="ck_account_payables_amount_nonnegative",
        ),
        CheckConstraint(
            "paid_amount >= 0",
            name="ck_account_payables_paid_amount_nonnegative",
        ),
        CheckConstraint(
            "paid_amount <= amount",
            name="ck_account_payables_paid_not_above_amount",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reference_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    supplier_name: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        default=Decimal("0.00"),
        server_default="0",
    )
    due_date: Mapped[date] = mapped_column(Date)
    status: Mapped[PayableStatus] = mapped_column(
        Enum(
            PayableStatus,
            name="payable_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=PayableStatus.UNPAID,
        server_default=PayableStatus.UNPAID.value,
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

    @hybrid_property
    def outstanding_amount(self) -> Decimal:
        return self.amount - self.paid_amount
