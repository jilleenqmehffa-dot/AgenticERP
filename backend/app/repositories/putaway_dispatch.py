from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.business_task import BusinessTask
from app.models.putaway_dispatch_request import PutawayDispatchRequest
from app.models.warehouse_location import WarehouseLocation


class PutawayDispatchRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(
        self,
        request_id: int,
    ) -> PutawayDispatchRequest | None:
        return await self._session.scalar(
            select(PutawayDispatchRequest)
            .where(PutawayDispatchRequest.id == request_id)
            .options(
                selectinload(PutawayDispatchRequest.source_bucket),
                selectinload(PutawayDispatchRequest.from_location).selectinload(
                    WarehouseLocation.warehouse
                ),
                selectinload(PutawayDispatchRequest.published_task).selectinload(
                    BusinessTask.items
                ),
            )
            .with_for_update()
        )

    async def get_by_generation_key(
        self,
        generation_key: str,
    ) -> PutawayDispatchRequest | None:
        return await self._session.scalar(
            select(PutawayDispatchRequest).where(
                PutawayDispatchRequest.generation_key == generation_key
            )
        )

    async def get_by_inspection_ids(
        self,
        inspection_ids: set[int],
    ) -> list[PutawayDispatchRequest]:
        if not inspection_ids:
            return []
        result = await self._session.scalars(
            select(PutawayDispatchRequest)
            .where(PutawayDispatchRequest.inspection_id.in_(inspection_ids))
            .options(
                selectinload(PutawayDispatchRequest.published_task).selectinload(
                    BusinessTask.items
                )
            )
            .order_by(PutawayDispatchRequest.id)
        )
        return list(result.unique())

    async def save(
        self,
        request: PutawayDispatchRequest,
    ) -> PutawayDispatchRequest:
        self._session.add(request)
        await self._session.flush()
        return request
