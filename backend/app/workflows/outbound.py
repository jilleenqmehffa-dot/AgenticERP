from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import OutboundStatus, ReservationStatus, TaskType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.stock_reservation import StockReservation
from app.repositories.outbound_order import OutboundOrderRepository
from app.repositories.stock_reservation import StockReservationRepository


class OutboundWorkflow:
    """Check PICK -> PACK -> STOCK_OUT results inside task execution."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        outbound_repository: OutboundOrderRepository | None = None,
        reservation_repository: StockReservationRepository | None = None,
    ) -> None:
        self._session = session
        self._outbound = outbound_repository or OutboundOrderRepository(session)
        self._reservations = reservation_repository or StockReservationRepository(session)

    async def after_task_completed_in_transaction(
        self, task: BusinessTask, *, trace_id: str
    ) -> None:
        if not self._session.in_transaction():
            raise RuntimeError(
                "after_task_completed_in_transaction requires an active transaction"
            )
        if task.task_type == TaskType.PICK:
            if task.source_type != "STOCK_RESERVATION":
                raise InvalidTaskDataError("PICK task must reference a reservation")
            reservation, item, order = await self._reservation_context(task)
            if (
                reservation.status != ReservationStatus.ACTIVE
                or item.picked_quantity <= 0
                or order.status != OutboundStatus.PICKING
            ):
                raise InvalidTaskDataError("PICK did not advance reserved stock")
        elif task.task_type == TaskType.PACK:
            if task.source_type != "OUTBOUND_ORDER_ITEM" or task.source_id is None:
                raise InvalidTaskDataError("PACK task must reference an outbound item")
            item = await self._outbound.get_item_for_update(task.source_id)
            if item is None:
                raise InvalidTaskDataError("PACK outbound item does not exist")
            order = await self._outbound.get_for_update(item.outbound_order_id)
            if (
                order is None
                or item.packed_at is None
                or item.picked_quantity != item.reserved_quantity
                or order.status not in {
                    OutboundStatus.PICKING,
                    OutboundStatus.READY_TO_SHIP,
                }
            ):
                raise InvalidTaskDataError("PACK did not complete the picked item")
        elif (
            task.task_type == TaskType.STOCK_OUT
            and task.source_type == "STOCK_RESERVATION"
        ):
            reservation, item, order = await self._reservation_context(task)
            if (
                reservation.status != ReservationStatus.CONSUMED
                or item.packed_at is None
                or item.shipped_quantity < reservation.quantity
                or order.status not in {
                    OutboundStatus.READY_TO_SHIP,
                    OutboundStatus.SHIPPED,
                }
            ):
                raise InvalidTaskDataError("STOCK_OUT did not ship packed stock")

    async def _reservation_context(
        self, task: BusinessTask
    ) -> tuple[StockReservation, OutboundOrderItem, OutboundOrder]:
        if task.source_id is None:
            raise InvalidTaskDataError("outbound task has no reservation source")
        reservation = await self._reservations.get_for_update(task.source_id)
        if reservation is None:
            raise InvalidTaskDataError("outbound reservation does not exist")
        item = await self._outbound.get_item_for_update(
            reservation.outbound_order_item_id
        )
        if item is None or item.product_id != reservation.product_id:
            raise InvalidTaskDataError("outbound reservation item does not match")
        order = await self._outbound.get_for_update(item.outbound_order_id)
        if order is None or order.warehouse_code != reservation.warehouse_code:
            raise InvalidTaskDataError("outbound reservation order does not match")
        return reservation, item, order
