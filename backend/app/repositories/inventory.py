from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import Inventory


class InventoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_product(self, product_id: int) -> list[Inventory]:
        result = await self._session.scalars(
            select(Inventory).where(Inventory.product_id == product_id)
        )
        return list(result.all())

    async def get_by_product_and_warehouse(
        self,
        product_id: int,
        warehouse_code: str,
    ) -> Inventory | None:
        return await self._session.scalar(
            select(Inventory).where(
                Inventory.product_id == product_id,
                Inventory.warehouse_code == warehouse_code,
            )
        )

    async def get_for_update(
        self,
        product_id: int,
        warehouse_code: str,
    ) -> Inventory | None:
        return await self._session.scalar(
            select(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.warehouse_code == warehouse_code,
            )
            .with_for_update()
        )

    async def save(self, inventory: Inventory) -> Inventory:
        self._session.add(inventory)
        await self._session.flush()
        return inventory
