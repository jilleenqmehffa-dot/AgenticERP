from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ReservationStatus
from app.db.base import Base


class StockReservation(Base):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="ck_stock_reservations_quantity_positive"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_no: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    outbound_order_item_id: Mapped[int] = mapped_column(
        ForeignKey("outbound_order_items.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    warehouse_code: Mapped[str] = mapped_column(String(64), index=True)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    status: Mapped[ReservationStatus] = mapped_column(
        Enum(
            ReservationStatus,
            name="reservation_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ReservationStatus.ACTIVE,
        server_default=ReservationStatus.ACTIVE.value,
    )
    reserved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
