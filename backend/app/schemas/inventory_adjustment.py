from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import AdjustmentStatus


class InventoryAdjustmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    count_item_id: int
    difference_quantity: Decimal
    status: AdjustmentStatus
    review_task_id: int | None
    adjustment_task_id: int | None
    reviewed_by_id: int | None
    reviewed_at: datetime | None
    review_reason: str | None
    applied_at: datetime | None


class PublishInventoryTask(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: int = Field(gt=0)


class PublishedInventoryTask(BaseModel):
    id: int
    task_no: str
    status: str
