from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inbound_receipt import InboundReceipt
from app.models.inbound_receipt_item import InboundReceiptItem


class InboundReceiptRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, receipt_id: int) -> InboundReceipt | None:
        return await self._session.scalar(
            select(InboundReceipt)
            .where(InboundReceipt.id == receipt_id)
            .with_for_update()
        )

    async def get_item(self, item_id: int) -> InboundReceiptItem | None:
        return await self._session.scalar(
            select(InboundReceiptItem).where(InboundReceiptItem.id == item_id)
        )

    async def get_items_for_update(
        self,
        receipt_id: int,
    ) -> list[InboundReceiptItem]:
        result = await self._session.scalars(
            select(InboundReceiptItem)
            .where(InboundReceiptItem.inbound_receipt_id == receipt_id)
            .order_by(InboundReceiptItem.id)
            .with_for_update()
        )
        return list(result)

    async def save(self, receipt: InboundReceipt) -> InboundReceipt:
        self._session.add(receipt)
        await self._session.flush()
        return receipt

    async def save_item(self, item: InboundReceiptItem) -> InboundReceiptItem:
        self._session.add(item)
        await self._session.flush()
        return item
