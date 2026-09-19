from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.audit import ensure_audit_payload_safe
from app.models.audit_log import AuditLog


class AuditLogRepository:
    """Append and query audit records; mutation operations are intentionally absent."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(self, audit_log: AuditLog) -> AuditLog:
        ensure_audit_payload_safe(audit_log.before_data, path="before_data")
        ensure_audit_payload_safe(audit_log.after_data, path="after_data")
        ensure_audit_payload_safe(audit_log.metadata_, path="metadata")
        self._session.add(audit_log)
        await self._session.flush()
        return audit_log

    async def get_by_trace(self, trace_id: str) -> list[AuditLog]:
        result = await self._session.scalars(
            select(AuditLog)
            .where(AuditLog.trace_id == trace_id)
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        return list(result.all())

    async def get_by_entity(
        self,
        entity_type: str,
        entity_id: str,
    ) -> list[AuditLog]:
        result = await self._session.scalars(
            select(AuditLog)
            .where(
                AuditLog.entity_type == entity_type,
                AuditLog.entity_id == entity_id,
            )
            .order_by(AuditLog.created_at, AuditLog.id)
        )
        return list(result.all())
