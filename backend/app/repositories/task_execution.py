from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_execution import TaskExecution


class TaskExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, execution_id: int) -> TaskExecution | None:
        return await self._session.scalar(
            select(TaskExecution)
            .where(TaskExecution.id == execution_id)
            .with_for_update()
        )

    async def get_for_task_submission_capability_for_update(
        self,
        task_id: int,
        submission_id: int,
        capability_name: str,
    ) -> TaskExecution | None:
        return await self._session.scalar(
            select(TaskExecution)
            .where(
                TaskExecution.task_id == task_id,
                TaskExecution.submission_id == submission_id,
                TaskExecution.capability_name == capability_name,
            )
            .with_for_update()
        )

    async def save(self, execution: TaskExecution) -> TaskExecution:
        self._session.add(execution)
        await self._session.flush()
        return execution
