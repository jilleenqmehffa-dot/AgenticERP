from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import ProductStatus
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.sales_order_item import SalesOrderItem


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(100))
    unit: Mapped[str] = mapped_column(String(32))
    status: Mapped[ProductStatus] = mapped_column(
        Enum(
            ProductStatus,
            name="product_status",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        ),
        default=ProductStatus.ACTIVE,
        server_default=ProductStatus.ACTIVE.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    sales_order_items: Mapped[list["SalesOrderItem"]] = relationship(
        back_populates="product",
    )
