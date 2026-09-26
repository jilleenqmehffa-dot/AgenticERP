from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem


class OutboundOrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, order_id: int) -> OutboundOrder | None:
        return await self._session.scalar(
            select(OutboundOrder)
            .where(OutboundOrder.id == order_id)
            .with_for_update()
        )

    async def get_item_for_update(self, item_id: int) -> OutboundOrderItem | None:
        return await self._session.scalar(
            select(OutboundOrderItem)
            .where(OutboundOrderItem.id == item_id)
            .with_for_update()
        )

    async def get_item(self, item_id: int) -> OutboundOrderItem | None:
        return await self._session.scalar(
            select(OutboundOrderItem).where(OutboundOrderItem.id == item_id)
        )

    async def get_items_for_update(self, order_id: int) -> list[OutboundOrderItem]:
        result = await self._session.scalars(
            select(OutboundOrderItem)
            .where(OutboundOrderItem.outbound_order_id == order_id)
            .order_by(OutboundOrderItem.id)
            .with_for_update()
        )
        return list(result)

    async def save_order(self, order: OutboundOrder) -> OutboundOrder:
        self._session.add(order)
        await self._session.flush()
        return order

    async def save_item(self, item: OutboundOrderItem) -> OutboundOrderItem:
        self._session.add(item)
        await self._session.flush()
        return item
