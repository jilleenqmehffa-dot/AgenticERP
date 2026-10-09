from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import StockStatus
from app.models.inventory_bucket import InventoryBucket


class InventoryBucketRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_location_for_update(
        self, product_id: int, warehouse_code: str, location_code: str
    ) -> list[InventoryBucket]:
        result = await self._session.scalars(
            select(InventoryBucket)
            .where(
                InventoryBucket.product_id == product_id,
                InventoryBucket.warehouse_code == warehouse_code,
                InventoryBucket.location_code == location_code,
            )
            .order_by(InventoryBucket.id)
            .with_for_update()
        )
        return list(result)

    async def get_for_update(
        self,
        product_id: int,
        warehouse_code: str,
        location_code: str,
        lot_no: str,
        stock_status: StockStatus,
    ) -> InventoryBucket | None:
        return await self._session.scalar(
            select(InventoryBucket)
            .where(
                InventoryBucket.product_id == product_id,
                InventoryBucket.warehouse_code == warehouse_code,
                InventoryBucket.location_code == location_code,
                InventoryBucket.lot_no == lot_no,
                InventoryBucket.stock_status == stock_status,
            )
            .with_for_update()
        )

    async def get_or_create_for_update(
        self,
        product_id: int,
        warehouse_code: str,
        location_code: str,
        lot_no: str,
        stock_status: StockStatus,
    ) -> InventoryBucket:
        await self._session.execute(
            insert(InventoryBucket)
            .values(
                product_id=product_id,
                warehouse_code=warehouse_code,
                location_code=location_code,
                lot_no=lot_no,
                stock_status=stock_status,
                quantity=0,
            )
            .on_conflict_do_nothing(
                constraint="uq_inventory_buckets_identity"
            )
        )
        bucket = await self.get_for_update(
            product_id,
            warehouse_code,
            location_code,
            lot_no,
            stock_status,
        )
        if bucket is None:
            raise RuntimeError("inventory bucket upsert did not return a row")
        return bucket

    async def save(self, bucket: InventoryBucket) -> InventoryBucket:
        self._session.add(bucket)
        await self._session.flush()
        return bucket
