from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ActorType, TaskStatus, TaskType
from app.schemas.business_task_item import (
    BusinessTaskItemCreate,
    BusinessTaskItemRead,
)
from app.schemas.inventory_count_item import (
    InventoryCountItemCreate,
    InventoryCountItemRead,
)


class BusinessTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_no: str = Field(min_length=1, max_length=64)
    task_type: TaskType
    warehouse_id: int = Field(gt=0)
    assignee_id: int = Field(gt=0)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, min_length=1)
    created_by_type: ActorType
    created_by_id: str | None = Field(default=None, min_length=1, max_length=255)
    items: list[BusinessTaskItemCreate] = Field(default_factory=list)
    inventory_count_items: list[InventoryCountItemCreate] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.source_type is None) != (self.source_id is None):
            raise ValueError("source_type and source_id must be provided together")
        return self


class BusinessTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: int | None = Field(default=None, gt=0)
    assignee_id: int | None = Field(default=None, gt=0)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: int | None = Field(default=None, gt=0)
    reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_update(self) -> Self:
        for field_name in ("warehouse_id", "assignee_id"):
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"{field_name} cannot be null")
        source_type_set = "source_type" in self.model_fields_set
        source_id_set = "source_id" in self.model_fields_set
        if source_type_set != source_id_set:
            raise ValueError("source_type and source_id must be updated together")
        return self


class BusinessTaskAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assignee_id: int = Field(gt=0)


class BusinessTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_no: str
    task_type: TaskType
    status: TaskStatus
    warehouse_id: int
    assignee_id: int
    source_type: str | None
    source_id: int | None
    reason: str | None
    created_by_type: ActorType
    created_by_id: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    failed_at: datetime | None
    updated_at: datetime
    items: list[BusinessTaskItemRead] = Field(default_factory=list)
    inventory_count_items: list[InventoryCountItemRead] = Field(default_factory=list)
