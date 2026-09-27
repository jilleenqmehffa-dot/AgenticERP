from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ReceiptInspection(Base):
    __tablename__ = "receipt_inspections"
    __table_args__ = (
        CheckConstraint(
            "received_quantity > 0 AND accepted_quantity >= 0 "
            "AND defective_quantity >= 0 AND quarantined_quantity >= 0 "
            "AND rejected_quantity >= 0",
            name="ck_receipt_inspections_quantities_nonnegative",
        ),
        CheckConstraint(
            "accepted_quantity + defective_quantity + quarantined_quantity "
            "+ rejected_quantity = received_quantity",
            name="ck_receipt_inspections_disposition_total",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inbound_receipt_item_id: Mapped[int] = mapped_column(
        ForeignKey("inbound_receipt_items.id", ondelete="CASCADE"), index=True
    )
    business_task_id: Mapped[int] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="RESTRICT"), unique=True
    )
    lot_no: Mapped[str] = mapped_column(String(100), default="", server_default="")
    received_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    accepted_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    defective_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    quarantined_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    rejected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    inspection_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    inspected_by_id: Mapped[int] = mapped_column(
        ForeignKey("employees.id", ondelete="RESTRICT"), index=True
    )
    inspected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
