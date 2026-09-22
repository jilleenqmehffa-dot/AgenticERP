from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class InventoryCountItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    location_id: int = Field(gt=0)
    system_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)


class InventoryCountItemRead(InventoryCountItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    counted_quantity: Decimal | None
    difference_quantity: Decimal | None
