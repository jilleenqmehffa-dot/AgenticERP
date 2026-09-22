from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

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

    warehouse: Mapped["Warehouse"] = relationship(back_populates="locations")
