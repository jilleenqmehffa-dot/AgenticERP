from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import StockStatus


class BusinessTaskItemCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int = Field(gt=0)
    from_location_id: int | None = Field(default=None, gt=0)
    to_location_id: int | None = Field(default=None, gt=0)
    source_bucket_id: int | None = Field(default=None, gt=0)
    target_stock_status: StockStatus | None = None
    planned_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)


class BusinessTaskItemRead(BusinessTaskItemCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    actual_quantity: Decimal | None
