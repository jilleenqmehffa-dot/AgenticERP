from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.inventory_count_item import InventoryCountItem


class BusinessTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, task_id: int) -> BusinessTask | None:
        return await self._session.scalar(
            select(BusinessTask)
            .where(BusinessTask.id == task_id)
            .options(selectinload(BusinessTask.warehouse))
            .with_for_update()
        )

    async def save(self, task: BusinessTask) -> BusinessTask:
        self._session.add(task)
        await self._session.flush()
        return task

    async def get_items_for_update(self, task_id: int) -> list[BusinessTaskItem]:
        result = await self._session.scalars(
            select(BusinessTaskItem)
            .where(BusinessTaskItem.task_id == task_id)
            .options(
                selectinload(BusinessTaskItem.source_bucket),
                selectinload(BusinessTaskItem.from_location),
                selectinload(BusinessTaskItem.to_location),
            )
            .order_by(BusinessTaskItem.id)
            .with_for_update()
        )
        return list(result)

    async def get_inventory_count_items_for_update(
        self,
        task_id: int,
    ) -> list[InventoryCountItem]:
        result = await self._session.scalars(
            select(InventoryCountItem)
            .where(InventoryCountItem.task_id == task_id)
            .order_by(InventoryCountItem.id)
            .with_for_update()
        )
        return list(result)

    async def save_inventory_count_item(
        self,
        item: InventoryCountItem,
    ) -> InventoryCountItem:
        self._session.add(item)
        await self._session.flush()
        return item
