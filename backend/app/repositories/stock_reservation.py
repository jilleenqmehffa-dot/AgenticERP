from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.stock_reservation import StockReservation


class StockReservationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, reservation_id: int) -> StockReservation | None:
        return await self._session.scalar(
            select(StockReservation)
            .where(StockReservation.id == reservation_id)
            .with_for_update()
        )

    async def get_by_no_for_update(
        self,
        reservation_no: str,
    ) -> StockReservation | None:
        return await self._session.scalar(
            select(StockReservation)
            .where(StockReservation.reservation_no == reservation_no)
            .with_for_update()
        )

    async def save(self, reservation: StockReservation) -> StockReservation:
        self._session.add(reservation)
        await self._session.flush()
        return reservation
