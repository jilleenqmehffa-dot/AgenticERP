from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import TransferStatus
from app.db.base import Base


class StockTransfer(Base):
    __tablename__ = "stock_transfers"
    __table_args__ = (
        CheckConstraint(
            "source_warehouse_code <> destination_warehouse_code",
            name="ck_stock_transfers_warehouses_different",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    transfer_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    destination_warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[TransferStatus] = mapped_column(
        Enum(
            TransferStatus,
            name="transfer_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=TransferStatus.DRAFT,
        server_default=TransferStatus.DRAFT.value,
    )
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
