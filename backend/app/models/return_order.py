from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Enum, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ReturnDirection, ReturnStatus
from app.db.base import Base


class ReturnOrder(Base):
    __tablename__ = "return_orders"
    __table_args__ = (
        CheckConstraint(
            "(source_type IS NULL) = (source_id IS NULL)",
            name="ck_return_orders_source_complete",
        ),
        Index("ix_return_orders_source", "source_type", "source_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    return_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    direction: Mapped[ReturnDirection] = mapped_column(
        Enum(
            ReturnDirection,
            name="return_direction",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    status: Mapped[ReturnStatus] = mapped_column(
        Enum(
            ReturnStatus,
            name="return_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ReturnStatus.REQUESTED,
        server_default=ReturnStatus.REQUESTED.value,
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
