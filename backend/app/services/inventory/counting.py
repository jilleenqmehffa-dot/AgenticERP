from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType
from app.core.exceptions import InvalidTaskDataError
from app.models.audit_log import AuditLog
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.warehouse_location import WarehouseLocationRepository

if TYPE_CHECKING:
    from app.models.inventory_count_item import InventoryCountItem


class InventoryCountService:
    def __init__(
        self,
        session: AsyncSession,
        task_repository: BusinessTaskRepository | None = None,
        location_repository: WarehouseLocationRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._locations = location_repository or WarehouseLocationRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def record_counts_in_transaction(
        self,
        items: list[InventoryCountItem],
        counts: dict[int, Decimal],
        *,
        warehouse_id: int,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> None:
        if not self._session.in_transaction():
            raise RuntimeError(
                "record_counts_in_transaction requires an active transaction"
            )
        expected_ids = {item.id for item in items}
        if not items or set(counts) != expected_ids:
            raise InvalidTaskDataError(
                "inventory count results must match all task count items"
            )
        normalized_counts: dict[int, Decimal] = {}
        for item_id, quantity in counts.items():
            try:
                normalized_quantity = Decimal(str(quantity))
            except (InvalidOperation, TypeError, ValueError):
                raise InvalidTaskDataError(
                    "counted quantity must be a nonnegative number"
                ) from None
            if not normalized_quantity.is_finite() or normalized_quantity < 0:
                raise InvalidTaskDataError(
                    "counted quantity must be a nonnegative number"
                )
            normalized_counts[item_id] = normalized_quantity

        identities: set[tuple[int, int]] = set()
        for item in items:
            identity = (item.product_id, item.location_id)
            if identity in identities:
                raise InvalidTaskDataError(
                    "inventory count task contains duplicate product and location"
                )
            identities.add(identity)
            location = await self._locations.get_for_update(item.location_id)
            if (
                location is None
                or location.warehouse_id != warehouse_id
                or not location.is_active
            ):
                raise InvalidTaskDataError(
                    "inventory count location is not active in the task warehouse"
                )
            if item.counted_quantity is not None:
                raise InvalidTaskDataError(
                    "inventory count item has already been recorded"
                )

            counted_quantity = normalized_counts[item.id]
            difference_quantity = counted_quantity - item.system_quantity
            item.counted_quantity = counted_quantity
            await self._tasks.save_inventory_count_item(item)
            await self._audits.append(
                AuditLog(
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action="COUNT_INVENTORY",
                    entity_type="INVENTORY_COUNT_ITEM",
                    entity_id=str(item.id),
                    before_data={
                        "counted_quantity": None,
                        "system_quantity": str(item.system_quantity),
                    },
                    after_data={
                        "counted_quantity": str(counted_quantity),
                        "difference_quantity": str(difference_quantity),
                    },
                    trace_id=trace_id,
                    metadata_={
                        "product_id": item.product_id,
                        "location_id": item.location_id,
                    },
                )
            )
