from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import OutboundStatus
from app.db.base import Base


class OutboundOrder(Base):
    __tablename__ = "outbound_orders"
    __table_args__ = (
        CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_outbound_orders_source_complete",
        ),
        Index("ix_outbound_orders_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    outbound_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[OutboundStatus] = mapped_column(
        Enum(
            OutboundStatus,
            name="outbound_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=OutboundStatus.PENDING_OUTBOUND,
        server_default=OutboundStatus.PENDING_OUTBOUND.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    reserved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    picking_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_to_ship_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    shipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
