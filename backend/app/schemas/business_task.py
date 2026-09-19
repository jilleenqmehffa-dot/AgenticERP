from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ActorType, TaskStatus, TaskType


class BusinessTaskCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_no: str = Field(min_length=1, max_length=64)
    task_type: TaskType
    assigned_employee_id: int = Field(gt=0)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: int | None = Field(default=None, gt=0)
    planned_data: dict[str, Any]
    created_by_type: ActorType
    created_by_id: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        if (self.source_type is None) != (self.source_id is None):
            raise ValueError("source_type and source_id must be provided together")
        return self


class BusinessTaskUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_employee_id: int | None = Field(default=None, gt=0)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: int | None = Field(default=None, gt=0)
    planned_data: dict[str, Any] | None = None

    @model_validator(mode="after")
    def validate_source_update(self) -> Self:
        if (
            "assigned_employee_id" in self.model_fields_set
            and self.assigned_employee_id is None
        ):
            raise ValueError("assigned_employee_id cannot be null")
        source_type_set = "source_type" in self.model_fields_set
        source_id_set = "source_id" in self.model_fields_set
        if source_type_set != source_id_set:
            raise ValueError("source_type and source_id must be updated together")
        return self


class BusinessTaskAssign(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assigned_employee_id: int = Field(gt=0)


class BusinessTaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_no: str
    task_type: TaskType
    status: TaskStatus
    assigned_employee_id: int | None
    source_type: str | None
    source_id: int | None
    planned_data: dict[str, Any]
    actual_data: dict[str, Any] | None
    exception_reason: str | None
    cancel_reason: str | None
    created_by_type: ActorType
    created_by_id: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    cancelled_at: datetime | None
