from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_task import BusinessTask


class BusinessTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, task_id: int) -> BusinessTask | None:
        return await self._session.scalar(
            select(BusinessTask).where(BusinessTask.id == task_id).with_for_update()
        )

    async def save(self, task: BusinessTask) -> BusinessTask:
        self._session.add(task)
        await self._session.flush()
        return task
