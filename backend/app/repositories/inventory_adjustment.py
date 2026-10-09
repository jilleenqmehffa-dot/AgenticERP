from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory_adjustment import InventoryAdjustment
from app.core.enums import AdjustmentStatus


class InventoryAdjustmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_status(self, status: AdjustmentStatus) -> list[InventoryAdjustment]:
        result = await self._session.scalars(
            select(InventoryAdjustment)
            .where(InventoryAdjustment.status == status)
            .order_by(InventoryAdjustment.id)
        )
        return list(result)

    async def get_for_update(self, adjustment_id: int) -> InventoryAdjustment | None:
        return await self._session.scalar(
            select(InventoryAdjustment)
            .where(InventoryAdjustment.id == adjustment_id)
            .with_for_update()
        )

    async def get_by_count_item_for_update(self, count_item_id: int) -> InventoryAdjustment | None:
        return await self._session.scalar(
            select(InventoryAdjustment)
            .where(InventoryAdjustment.count_item_id == count_item_id)
            .with_for_update()
        )

    async def save(self, adjustment: InventoryAdjustment) -> InventoryAdjustment:
        self._session.add(adjustment)
        await self._session.flush()
        return adjustment
