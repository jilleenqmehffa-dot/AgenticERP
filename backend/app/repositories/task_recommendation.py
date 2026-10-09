from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task_recommendation import TaskRecommendation


class TaskRecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, recommendation_id: int) -> TaskRecommendation | None:
        return await self._session.scalar(
            select(TaskRecommendation)
            .where(TaskRecommendation.id == recommendation_id)
            .with_for_update()
        )

    async def get_by_no_for_update(self, recommendation_no: str) -> TaskRecommendation | None:
        return await self._session.scalar(
            select(TaskRecommendation)
            .where(TaskRecommendation.recommendation_no == recommendation_no)
            .with_for_update()
        )

    async def save(self, recommendation: TaskRecommendation) -> TaskRecommendation:
        self._session.add(recommendation)
        await self._session.flush()
        return recommendation
