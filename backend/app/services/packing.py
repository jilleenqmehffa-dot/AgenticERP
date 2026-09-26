from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType
from app.core.exceptions import (
    InvalidPackingDataError,
    OutboundOrderItemNotFoundError,
)
from app.models.audit_log import AuditLog
from app.models.outbound_order_item import OutboundOrderItem
from app.repositories.audit_log import AuditLogRepository
from app.repositories.outbound_order import OutboundOrderRepository


class PackingService:
    def __init__(
        self,
        session: AsyncSession,
        outbound_repository: OutboundOrderRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._outbound = outbound_repository or OutboundOrderRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def mark_packed(
        self,
        outbound_order_item_id: int,
        *,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> OutboundOrderItem:
        values = self._validate(
            outbound_order_item_id=outbound_order_item_id,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        async with self._session.begin():
            return await self._mark_packed_in_transaction(**values)

    async def mark_packed_in_transaction(
        self,
        outbound_order_item_id: int,
        *,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> OutboundOrderItem:
        if not self._session.in_transaction():
            raise RuntimeError(
                "mark_packed_in_transaction requires an active transaction"
            )
        values = self._validate(
            outbound_order_item_id=outbound_order_item_id,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        return await self._mark_packed_in_transaction(**values)

    async def _mark_packed_in_transaction(
        self,
        *,
        outbound_order_item_id: int,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> OutboundOrderItem:
        item = await self._outbound.get_item_for_update(outbound_order_item_id)
        if item is None:
            raise OutboundOrderItemNotFoundError(outbound_order_item_id)
        if item.packed_at is not None:
            return item

        item.packed_at = datetime.now(timezone.utc)
        await self._outbound.save_item(item)
        await self._audits.append(
            AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                action="PACK_GOODS",
                entity_type="OUTBOUND_ORDER_ITEM",
                entity_id=str(item.id),
                before_data={"packed": False},
                after_data={"packed": True, "packed_at": item.packed_at.isoformat()},
                trace_id=trace_id,
                metadata_={"product_id": item.product_id},
            )
        )
        return item

    @classmethod
    def _validate(cls, **values: object) -> dict[str, object]:
        actor_type = cls._actor_type(values["actor_type"])
        return {
            "outbound_order_item_id": cls._positive_id(
                values["outbound_order_item_id"], "outbound_order_item_id"
            ),
            "actor_type": actor_type,
            "actor_id": cls._actor_id(actor_type, values["actor_id"]),
            "trace_id": cls._trace_id(values["trace_id"]),
        }

    @staticmethod
    def _positive_id(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidPackingDataError(
                f"{field_name} must be a positive integer"
            )
        return value

    @staticmethod
    def _actor_type(value: object) -> ActorType:
        try:
            return ActorType(value)
        except (TypeError, ValueError):
            raise InvalidPackingDataError("invalid actor_type") from None

    @staticmethod
    def _actor_id(actor_type: ActorType, value: object) -> str:
        if value is None and actor_type == ActorType.SYSTEM:
            return ActorType.SYSTEM.value
        if not isinstance(value, str) or not value.strip():
            raise InvalidPackingDataError("actor_id is required")
        return value.strip()

    @staticmethod
    def _trace_id(value: object) -> str:
        if value is None:
            return str(uuid4())
        if not isinstance(value, str) or not value.strip():
            raise InvalidPackingDataError("trace_id must be a nonempty string")
        return value.strip()
