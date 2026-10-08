from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.warehouse import Warehouse


class WarehouseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, warehouse_id: int) -> Warehouse | None:
        return await self._session.scalar(
            select(Warehouse).where(Warehouse.id == warehouse_id)
        )
