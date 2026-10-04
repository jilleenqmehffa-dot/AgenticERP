from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import (
    ActorType,
    DispatchRequestStatus,
    StockStatus,
    WarehouseLocationType,
)
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.business_task import BusinessTask
    from app.models.inventory_bucket import InventoryBucket
    from app.models.receipt_inspection import ReceiptInspection
    from app.models.warehouse_location import WarehouseLocation


class PutawayDispatchRequest(Base):
    __tablename__ = "putaway_dispatch_requests"
    __table_args__ = (
        CheckConstraint(
            "planned_quantity > 0",
            name="ck_putaway_dispatch_requests_quantity_positive",
        ),
        CheckConstraint(
            "status != 'PUBLISHED' OR "
            "(published_task_id IS NOT NULL AND published_by_type IS NOT NULL "
            "AND published_by_id IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_putaway_dispatch_requests_published_complete",
        ),
        CheckConstraint(
            "status != 'PUBLISHED' OR published_by_type != 'SYSTEM'",
            name="ck_putaway_dispatch_requests_publisher_not_system",
        ),
        UniqueConstraint(
            "generation_key",
            name="uq_putaway_dispatch_requests_generation_key",
        ),
        UniqueConstraint(
            "published_task_id",
            name="uq_putaway_dispatch_requests_published_task",
        ),
        Index(
            "ix_putaway_dispatch_requests_warehouse_status",
            "warehouse_id",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    inspection_id: Mapped[int] = mapped_column(
        ForeignKey("receipt_inspections.id", ondelete="RESTRICT"),
        index=True,
    )
    source_bucket_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_buckets.id", ondelete="RESTRICT"),
        index=True,
    )
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="RESTRICT"),
        index=True,
    )
    from_location_id: Mapped[int] = mapped_column(
        ForeignKey("warehouse_locations.id", ondelete="RESTRICT"),
        index=True,
    )
    required_location_type: Mapped[WarehouseLocationType] = mapped_column(
        Enum(
            WarehouseLocationType,
            name="putaway_dispatch_location_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    target_stock_status: Mapped[StockStatus] = mapped_column(
        Enum(
            StockStatus,
            name="putaway_dispatch_target_stock_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    planned_quantity: Mapped[Decimal] = mapped_column(Numeric(18, 3))
    generation_key: Mapped[str] = mapped_column(String(128))
    status: Mapped[DispatchRequestStatus] = mapped_column(
        Enum(
            DispatchRequestStatus,
            name="dispatch_request_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=DispatchRequestStatus.PENDING,
        server_default=DispatchRequestStatus.PENDING.value,
    )
    published_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("business_tasks.id", ondelete="SET NULL"),
        nullable=True,
    )
    published_by_type: Mapped[ActorType | None] = mapped_column(
        Enum(
            ActorType,
            name="putaway_dispatch_actor_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        nullable=True,
    )
    published_by_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    inspection: Mapped["ReceiptInspection"] = relationship()
    source_bucket: Mapped["InventoryBucket"] = relationship()
    from_location: Mapped["WarehouseLocation"] = relationship()
    published_task: Mapped["BusinessTask | None"] = relationship()
