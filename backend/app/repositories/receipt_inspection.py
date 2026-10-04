from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.receipt_inspection import ReceiptInspection


class ReceiptInspectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, inspection_id: int) -> ReceiptInspection | None:
        return await self._session.scalar(
            select(ReceiptInspection).where(ReceiptInspection.id == inspection_id)
        )

    async def get_by_receipt_item_ids(
        self,
        receipt_item_ids: set[int],
    ) -> list[ReceiptInspection]:
        if not receipt_item_ids:
            return []
        result = await self._session.scalars(
            select(ReceiptInspection)
            .where(ReceiptInspection.inbound_receipt_item_id.in_(receipt_item_ids))
            .order_by(ReceiptInspection.id)
        )
        return list(result)

    async def save(self, inspection: ReceiptInspection) -> ReceiptInspection:
        self._session.add(inspection)
        await self._session.flush()
        return inspection
