from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.core.enums import WarehouseLocationType

if TYPE_CHECKING:
    from app.models.warehouse import Warehouse


class WarehouseLocation(Base):
    __tablename__ = "warehouse_locations"
    __table_args__ = (
        UniqueConstraint(
            "warehouse_id",
            "code",
            name="uq_warehouse_locations_warehouse_code",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    warehouse_id: Mapped[int] = mapped_column(
        ForeignKey("warehouses.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64))
    location_type: Mapped[WarehouseLocationType] = mapped_column(
        Enum(
            WarehouseLocationType,
            name="warehouse_location_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=WarehouseLocationType.STORAGE,
        server_default=WarehouseLocationType.STORAGE.value,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true"
    )

    warehouse: Mapped["Warehouse"] = relationship(back_populates="locations")
