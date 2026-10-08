import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.capabilities.picking import PickCapability
from app.core.enums import (
    ActorType,
    OutboundStatus,
    ReservationStatus,
    StockStatus,
    TaskType,
    WarehouseLocationType,
)
from app.core.exceptions import (
    InvalidPickingDataError,
    InvalidPickingStateError,
    InvalidTaskDataError,
)
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.inventory_bucket import InventoryBucket
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.stock_reservation import StockReservation
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation
from app.services.outbound.picking import PickingService


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session

    async def __aenter__(self) -> "FakeTransaction":
        self.session.active = True
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        self.session.active = False
        return False


class FakeSession:
    def __init__(self) -> None:
        self.active = False

    def begin(self) -> FakeTransaction:
        return FakeTransaction(self)

    def in_transaction(self) -> bool:
        return self.active


class PickingServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.reservation = StockReservation(
            id=401,
            reservation_no="RES-401",
            outbound_order_item_id=301,
            product_id=201,
            warehouse_code="WH-A",
            location_code="STORAGE-A",
            lot_no="LOT-1",
            quantity=Decimal("10.000"),
            status=ReservationStatus.ACTIVE,
        )
        self.order = OutboundOrder(
            id=101,
            outbound_no="OUT-101",
            warehouse_code="WH-A",
            status=OutboundStatus.RESERVED,
        )
        self.item = OutboundOrderItem(
            id=301,
            outbound_order_id=101,
            product_id=201,
            requested_quantity=Decimal("10.000"),
            reserved_quantity=Decimal("10.000"),
            picked_quantity=Decimal("0.000"),
            shipped_quantity=Decimal("0.000"),
        )
        self.reservations = MagicMock()
        self.reservations.get_for_update = AsyncMock(return_value=self.reservation)
        self.reservations.save = AsyncMock(side_effect=lambda value: value)
        self.outbound = MagicMock()
        self.outbound.get_item = AsyncMock(return_value=self.item)
        self.outbound.get_for_update = AsyncMock(return_value=self.order)
        self.outbound.get_item_for_update = AsyncMock(return_value=self.item)
        self.outbound.save_item = AsyncMock(side_effect=lambda value: value)
        self.outbound.save_order = AsyncMock(side_effect=lambda value: value)
        self.buckets = MagicMock()
        self.buckets.move_in_transaction = AsyncMock()
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda value: value)
        self.service = PickingService(
            self.session,  # type: ignore[arg-type]
            self.reservations,
            self.outbound,
            self.buckets,
            self.audits,
        )

    def pick_kwargs(self) -> dict[str, object]:
        return {
            "quantity": Decimal("10.000"),
            "to_location_code": "SHIPPING-A",
            "expected_product_id": 201,
            "expected_from_location_code": "STORAGE-A",
            "expected_lot_no": "LOT-1",
            "actor_type": ActorType.EMPLOYEE,
            "actor_id": "23",
            "trace_id": "trace-pick",
        }

    async def test_pick_moves_reserved_bucket_without_shipping_inventory(self) -> None:
        result = await self.service.pick(401, **self.pick_kwargs())

        self.assertIs(result, self.reservation)
        move = self.buckets.move_in_transaction.await_args
        self.assertEqual(move.kwargs["from_status"], StockStatus.RESERVED)
        self.assertEqual(move.kwargs["to_status"], StockStatus.PICKING)
        self.assertEqual(move.kwargs["to_location_code"], "SHIPPING-A")
        self.assertEqual(self.reservation.location_code, "SHIPPING-A")
        self.assertEqual(self.reservation.status, ReservationStatus.ACTIVE)
        self.assertEqual(self.item.picked_quantity, Decimal("10.000"))
        self.assertEqual(self.order.status, OutboundStatus.PICKING)
        self.assertIsNotNone(self.order.picking_started_at)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "PICK_RESERVED_STOCK")

    async def test_pick_rejects_partial_quantity_and_inactive_reservation(self) -> None:
        partial = {**self.pick_kwargs(), "quantity": Decimal("9.000")}
        with self.assertRaises(InvalidPickingDataError):
            await self.service.pick(401, **partial)

        self.reservation.status = ReservationStatus.RELEASED
        with self.assertRaises(InvalidPickingStateError):
            await self.service.pick(401, **self.pick_kwargs())

        self.buckets.move_in_transaction.assert_not_awaited()

    async def test_pick_in_transaction_requires_outer_transaction(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "active transaction"):
            await self.service.pick_in_transaction(401, **self.pick_kwargs())


class PickCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.picking = MagicMock()
        self.picking.pick_in_transaction = AsyncMock()
        self.capability = PickCapability(self.picking)
        self.task = BusinessTask(
            id=1001,
            task_no="PICK-1001",
            task_type=TaskType.PICK,
            warehouse_id=1,
            assignee_id=23,
            source_type="STOCK_RESERVATION",
            source_id=401,
        )
        self.task.warehouse = Warehouse(id=1, code="WH-A", name="Warehouse A")
        source_location = WarehouseLocation(
            id=11,
            warehouse_id=1,
            code="STORAGE-A",
            location_type=WarehouseLocationType.STORAGE,
            is_active=True,
        )
        shipping_location = WarehouseLocation(
            id=12,
            warehouse_id=1,
            code="SHIPPING-A",
            location_type=WarehouseLocationType.SHIPPING,
            is_active=True,
        )
        source_bucket = InventoryBucket(
            id=501,
            product_id=201,
            warehouse_code="WH-A",
            location_code="STORAGE-A",
            lot_no="LOT-1",
            stock_status=StockStatus.RESERVED,
            quantity=Decimal("10.000"),
        )
        self.item = BusinessTaskItem(
            id=601,
            task_id=1001,
            product_id=201,
            from_location_id=11,
            to_location_id=12,
            source_bucket_id=501,
            target_stock_status=StockStatus.PICKING,
            planned_quantity=Decimal("10.000"),
        )
        self.item.from_location = source_location
        self.item.to_location = shipping_location
        self.item.source_bucket = source_bucket
        self.employee = Employee(id=23)

    async def test_capability_executes_picking_service(self) -> None:
        validated = self.capability.validate(
            self.task,
            [self.item],
            {"actual_quantity": "10.000"},
        )
        await self.capability.execute(
            self.task,
            self.employee,
            validated,
            "trace-pick",
        )

        call = self.picking.pick_in_transaction.await_args
        self.assertEqual(call.args, (401,))
        self.assertEqual(call.kwargs["to_location_code"], "SHIPPING-A")
        self.assertEqual(call.kwargs["expected_lot_no"], "LOT-1")
        self.assertEqual(self.item.actual_quantity, Decimal("10.000"))

    def test_capability_rejects_non_shipping_target(self) -> None:
        self.item.to_location.location_type = WarehouseLocationType.STORAGE

        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(
                self.task,
                [self.item],
                {"actual_quantity": "10.000"},
            )


if __name__ == "__main__":
    unittest.main()
