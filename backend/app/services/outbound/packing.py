from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, OutboundStatus
from app.core.exceptions import (
    InvalidPackingDataError,
    OutboundOrderItemNotFoundError,
)
from app.core.validation import (
    actor_id as validate_actor_id,
    actor_type as validate_actor_type,
    positive_int,
    trace_id as validate_trace_id,
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
        item_reference = await self._outbound.get_item(outbound_order_item_id)
        if item_reference is None:
            raise OutboundOrderItemNotFoundError(outbound_order_item_id)
        order = await self._outbound.get_for_update(item_reference.outbound_order_id)
        if order is None:
            raise InvalidPackingDataError("outbound order does not exist")
        if order.status not in {
            OutboundStatus.PICKING,
            OutboundStatus.READY_TO_SHIP,
        }:
            raise InvalidPackingDataError("outbound order is not being packed")
        items = await self._outbound.get_items_for_update(order.id)
        item = next(
            (candidate for candidate in items if candidate.id == outbound_order_item_id),
            None,
        )
        if item is None:
            raise OutboundOrderItemNotFoundError(outbound_order_item_id)
        if item.packed_at is not None:
            return item
        if item.picked_quantity != item.reserved_quantity:
            raise InvalidPackingDataError(
                "outbound order item must be fully picked before packing"
            )

        item.packed_at = datetime.now(timezone.utc)
        await self._outbound.save_item(item)
        if all(
            candidate.packed_at is not None
            and candidate.picked_quantity == candidate.reserved_quantity
            for candidate in items
        ):
            order.status = OutboundStatus.READY_TO_SHIP
            order.ready_to_ship_at = datetime.now(timezone.utc)
            await self._outbound.save_order(order)
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
        return positive_int(value, field_name, error=InvalidPackingDataError)

    @staticmethod
    def _actor_type(value: object) -> ActorType:
        return validate_actor_type(
            value,
            coerce=True,
            error=InvalidPackingDataError,
        )

    @staticmethod
    def _actor_id(actor_type: ActorType, value: object) -> str:
        return validate_actor_id(
            actor_type,
            value,
            error=InvalidPackingDataError,
        )

    @staticmethod
    def _trace_id(value: object) -> str:
        return validate_trace_id(value, error=InvalidPackingDataError)
