from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem


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
