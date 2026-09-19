from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, Enum, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ActorType
from app.db.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint(
            "length(btrim(actor_id)) > 0",
            name="ck_audit_logs_actor_id_not_blank",
        ),
        CheckConstraint(
            "length(btrim(action)) > 0",
            name="ck_audit_logs_action_not_blank",
        ),
        CheckConstraint(
            "length(btrim(entity_type)) > 0",
            name="ck_audit_logs_entity_type_not_blank",
        ),
        CheckConstraint(
            "length(btrim(entity_id)) > 0",
            name="ck_audit_logs_entity_id_not_blank",
        ),
        CheckConstraint(
            "length(btrim(trace_id)) > 0",
            name="ck_audit_logs_trace_id_not_blank",
        ),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_actor", "actor_type", "actor_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_type: Mapped[ActorType] = mapped_column(
        Enum(
            ActorType,
            name="actor_type",
            native_enum=False,
            create_constraint=True,
            validate_strings=True,
        )
    )
    actor_id: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(100))
    entity_type: Mapped[str] = mapped_column(String(100))
    entity_id: Mapped[str] = mapped_column(String(255))
    before_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    after_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    trace_id: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
