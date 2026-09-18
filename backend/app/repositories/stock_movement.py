from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_movement import StockMovement


class StockMovementRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, movement: StockMovement) -> StockMovement:
        self._session.add(movement)
        await self._session.flush()
        return movement
