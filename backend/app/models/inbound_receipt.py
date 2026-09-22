from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ReceiptStatus
from app.db.base import Base


class InboundReceipt(Base):
    __tablename__ = "inbound_receipts"
    __table_args__ = (
        CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_inbound_receipts_source_complete",
        ),
        Index("ix_inbound_receipts_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[ReceiptStatus] = mapped_column(
        Enum(
            ReceiptStatus,
            name="receipt_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ReceiptStatus.PENDING_RECEIPT,
        server_default=ReceiptStatus.PENDING_RECEIPT.value,
    )
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inspection_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    inspected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
