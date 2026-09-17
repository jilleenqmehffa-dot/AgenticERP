from datetime import datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import InventoryStatus


class InventoryBase(BaseModel):
    warehouse_code: str = Field(min_length=1, max_length=64)
    on_hand_quantity: Decimal = Field(
        default=Decimal("0.000"), ge=0, max_digits=18, decimal_places=3
    )
    reserved_quantity: Decimal = Field(
        default=Decimal("0.000"), ge=0, max_digits=18, decimal_places=3
    )
    status: InventoryStatus = InventoryStatus.OUT_OF_STOCK
    low_stock_threshold: Decimal = Field(
        default=Decimal("0.000"), ge=0, max_digits=18, decimal_places=3
    )

    @model_validator(mode="after")
    def validate_reserved_quantity(self) -> Self:
        if self.reserved_quantity > self.on_hand_quantity:
            raise ValueError("reserved_quantity cannot exceed on_hand_quantity")
        return self


class InventoryCreate(InventoryBase):
    product_id: int = Field(gt=0)


class InventoryUpdate(BaseModel):
    low_stock_threshold: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=3,
    )


class InventoryRead(InventoryBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    product_id: int
    available_quantity: Decimal
    updated_at: datetime
