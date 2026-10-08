from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.warehouse_location import WarehouseLocation


class WarehouseLocationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, location_id: int) -> WarehouseLocation | None:
        return await self._session.scalar(
            select(WarehouseLocation)
            .where(WarehouseLocation.id == location_id)
            .with_for_update()
        )

    async def get_by_warehouse_and_code(
        self, warehouse_id: int, code: str
    ) -> WarehouseLocation | None:
        return await self._session.scalar(
            select(WarehouseLocation).where(
                WarehouseLocation.warehouse_id == warehouse_id,
                WarehouseLocation.code == code,
            )
        )
