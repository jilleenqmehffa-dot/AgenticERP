from sqlalchemy.ext.asyncio import AsyncSession

from app.models.receipt_inspection import ReceiptInspection


class ReceiptInspectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, inspection: ReceiptInspection) -> ReceiptInspection:
        self._session.add(inspection)
        await self._session.flush()
        return inspection
