from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import SubmissionStatus
from app.models.task_submission import TaskSubmission


class TaskSubmissionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_for_update(self, task_id: int) -> TaskSubmission | None:
        return await self._session.scalar(
            select(TaskSubmission)
            .where(TaskSubmission.task_id == task_id)
            .order_by(TaskSubmission.version.desc())
            .limit(1)
            .with_for_update()
        )

    async def get_pending_for_update(self, task_id: int) -> TaskSubmission | None:
        return await self._session.scalar(
            select(TaskSubmission)
            .where(
                TaskSubmission.task_id == task_id,
                TaskSubmission.status == SubmissionStatus.PENDING_REVIEW,
            )
            .order_by(TaskSubmission.version.desc())
            .limit(1)
            .with_for_update()
        )

    async def save(self, submission: TaskSubmission) -> TaskSubmission:
        self._session.add(submission)
        await self._session.flush()
        return submission
