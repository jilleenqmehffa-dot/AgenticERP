from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import (
    ActorType,
    ExecutionStatus,
    RecommendationStatus,
    SubmissionStatus,
    TaskType,
)


class TaskRecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_no: str = Field(min_length=1, max_length=64)
    task_type: TaskType
    warehouse_id: int = Field(gt=0)
    source_type: str | None = Field(default=None, min_length=1, max_length=64)
    source_id: int | None = Field(default=None, gt=0)
    proposed_assignee_id: int | None = Field(default=None, gt=0)
    rationale: str = Field(min_length=1)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    proposed_data: dict[str, Any] = Field(default_factory=dict)
    suggested_by_type: ActorType = ActorType.AGENT
    suggested_by_id: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_source_and_actor(self) -> "TaskRecommendationCreate":
        if (self.source_type is None) != (self.source_id is None):
            raise ValueError("source_type and source_id must be provided together")
        if self.suggested_by_type != ActorType.AGENT:
            raise ValueError("task recommendations must be created by an agent")
        return self


class TaskRecommendationRead(TaskRecommendationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: RecommendationStatus
    reviewed_by_id: int | None
    review_reason: str | None
    reviewed_at: datetime | None
    approved_task_id: int | None
    created_at: datetime
    updated_at: datetime


class TaskSubmissionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form_data: dict[str, Any]


class StockTaskSubmissionForm(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actual_quantity: int = Field(gt=0)
    remark: str | None = Field(default=None, min_length=1, max_length=2000)


class TaskSubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    version: int
    status: SubmissionStatus
    form_data: dict[str, Any]
    payload_hash: str
    submitted_by_id: int
    submitted_at: datetime
    reviewed_by_id: int | None
    review_reason: str | None
    reviewed_at: datetime | None


class TaskExecutionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    submission_id: int
    capability_name: str
    idempotency_key: str
    status: ExecutionStatus
    attempt_count: int
    error_code: str | None
    error_message: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime
