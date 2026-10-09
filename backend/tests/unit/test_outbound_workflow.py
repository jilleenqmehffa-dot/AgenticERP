import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import OutboundStatus, ReservationStatus, TaskType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.stock_reservation import StockReservation
from app.workflows.outbound import OutboundWorkflow


class OutboundWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.in_transaction.return_value = True
        self.reservation = StockReservation(
            id=1,
            outbound_order_item_id=2,
            product_id=3,
            warehouse_code="WH-A",
            quantity=Decimal("5"),
            status=ReservationStatus.ACTIVE,
        )
        self.item = OutboundOrderItem(
            id=2,
            outbound_order_id=4,
            product_id=3,
            requested_quantity=Decimal("5"),
            reserved_quantity=Decimal("5"),
            picked_quantity=Decimal("5"),
            shipped_quantity=Decimal("0"),
        )
        self.order = OutboundOrder(
            id=4, warehouse_code="WH-A", status=OutboundStatus.PICKING
        )
        self.reservations = MagicMock()
        self.reservations.get_for_update = AsyncMock(return_value=self.reservation)
        self.outbound = MagicMock()
        self.outbound.get_item_for_update = AsyncMock(return_value=self.item)
        self.outbound.get_for_update = AsyncMock(return_value=self.order)
        self.workflow = OutboundWorkflow(
            session,
            outbound_repository=self.outbound,
            reservation_repository=self.reservations,
        )

    async def test_pick_pack_ship_sequence(self) -> None:
        task = BusinessTask(task_type=TaskType.PICK, source_type="STOCK_RESERVATION", source_id=1)
        await self.workflow.after_task_completed_in_transaction(task, trace_id="trace")

        task.task_type = TaskType.PACK
        task.source_type = "OUTBOUND_ORDER_ITEM"
        task.source_id = 2
        with self.assertRaises(InvalidTaskDataError):
            await self.workflow.after_task_completed_in_transaction(task, trace_id="trace")
        self.item.packed_at = datetime.now(timezone.utc)
        self.order.status = OutboundStatus.READY_TO_SHIP
        await self.workflow.after_task_completed_in_transaction(task, trace_id="trace")

        task.task_type = TaskType.STOCK_OUT
        task.source_type = "STOCK_RESERVATION"
        task.source_id = 1
        with self.assertRaises(InvalidTaskDataError):
            await self.workflow.after_task_completed_in_transaction(task, trace_id="trace")
        self.reservation.status = ReservationStatus.CONSUMED
        self.item.shipped_quantity = Decimal("5")
        self.order.status = OutboundStatus.SHIPPED
        await self.workflow.after_task_completed_in_transaction(task, trace_id="trace")


if __name__ == "__main__":
    unittest.main()
