from datetime import datetime
from typing import Any, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ActorType
from app.domain.audit import ensure_audit_payload_safe


class AuditLogCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor_type: ActorType
    actor_id: str = Field(min_length=1, max_length=255)
    action: str = Field(min_length=1, max_length=100)
    entity_type: str = Field(min_length=1, max_length=100)
    entity_id: str = Field(min_length=1, max_length=255)
    before_data: dict[str, Any] | None = None
    after_data: dict[str, Any] | None = None
    trace_id: str = Field(min_length=1, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def reject_sensitive_data(self) -> Self:
        ensure_audit_payload_safe(self.before_data, path="before_data")
        ensure_audit_payload_safe(self.after_data, path="after_data")
        ensure_audit_payload_safe(self.metadata, path="metadata")
        return self


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor_type: ActorType
    actor_id: str
    action: str
    entity_type: str
    entity_id: str
    before_data: dict[str, Any] | None
    after_data: dict[str, Any] | None
    trace_id: str
    created_at: datetime
    metadata: dict[str, Any] = Field(
        validation_alias=AliasChoices("metadata_", "metadata")
    )
