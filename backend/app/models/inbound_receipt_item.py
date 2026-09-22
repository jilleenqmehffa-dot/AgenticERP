from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InboundReceiptItem(Base):
    __tablename__ = "inbound_receipt_items"
    __table_args__ = (
        CheckConstraint("expected_quantity > 0", name="ck_receipt_items_expected_positive"),
        CheckConstraint(
            "received_quantity >= 0 AND received_quantity <= expected_quantity",
            name="ck_receipt_items_received_valid",
        ),
        CheckConstraint(
            "accepted_quantity >= 0 AND defective_quantity >= 0 "
            "AND quarantined_quantity >= 0 AND rejected_quantity >= 0",
            name="ck_receipt_items_disposition_nonnegative",
        ),
        CheckConstraint(
            "accepted_quantity + defective_quantity + quarantined_quantity "
            "+ rejected_quantity <= received_quantity",
            name="ck_receipt_items_disposition_within_received",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inbound_receipt_id: Mapped[int] = mapped_column(
        ForeignKey("inbound_receipts.id", ondelete="CASCADE"), index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    expected_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    received_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    accepted_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    defective_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    quarantined_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
    rejected_quantity: Mapped[Decimal] = mapped_column(
        Numeric(18, 3), default=Decimal("0.000"), server_default="0"
    )
