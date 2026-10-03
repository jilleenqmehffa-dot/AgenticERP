import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import (
    EmployeeStatus,
    ExecutionStatus,
    OutboundStatus,
    ReservationStatus,
    SubmissionStatus,
    StockStatus,
    TaskStatus,
    TaskType,
    WarehouseLocationType,
)
from app.core.exceptions import (
    InvalidTaskDataError,
    InvalidTaskExecutionStateError,
    TaskExecutionAlreadyRunningError,
)
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.inventory_bucket import InventoryBucket
from app.models.inventory_count_item import InventoryCountItem
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.stock_reservation import StockReservation
from app.models.task_execution import TaskExecution
from app.models.task_submission import TaskSubmission
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation
from app.services.capability_execution import CapabilityExecutionService


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session
        self.exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeTransaction":
        self.session.active = True
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        self.exception_type = exception_type
        self.session.active = False
        return False


class FakeSession:
    def __init__(self) -> None:
        self.transactions: list[FakeTransaction] = []
        self.active = False

    def begin(self) -> FakeTransaction:
        transaction = FakeTransaction(self)
        self.transactions.append(transaction)
        return transaction

    def in_transaction(self) -> bool:
        return self.active


class CapabilityExecutionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.task = BusinessTask(
            id=1001,
            task_no="TASK-1001",
            task_type=TaskType.STOCK_OUT,
            status=TaskStatus.APPROVED_FOR_EXECUTION,
            warehouse_id=1,
            assignee_id=23,
        )
        self.task.warehouse = Warehouse(id=1, code="WH-A", name="Warehouse A")
        self.item = BusinessTaskItem(
            id=101,
            task_id=1001,
            product_id=1,
            from_location_id=11,
            to_location_id=None,
            planned_quantity=Decimal("50"),
            actual_quantity=None,
        )
        self.submission = TaskSubmission(
            id=501,
            task_id=1001,
            version=1,
            status=SubmissionStatus.APPROVED,
            form_data={"actual_quantity": 40, "remark": "实际出库40件"},
            payload_hash="a" * 64,
            submitted_by_id=23,
            reviewed_by_id=99,
        )
        self.execution = TaskExecution(
            id=701,
            task_id=1001,
            submission_id=501,
            capability_name="STOCK_OUT",
            idempotency_key="b" * 64,
            status=ExecutionStatus.PENDING,
            attempt_count=0,
        )
        self.executor = Employee(id=23, status=EmployeeStatus.ACTIVE)
        self.executions = MagicMock()
        self.executions.get_for_update = AsyncMock(return_value=self.execution)
        self.executions.save = AsyncMock(side_effect=lambda execution: execution)
        self.tasks = MagicMock()
        self.tasks.get_for_update = AsyncMock(return_value=self.task)
        self.tasks.get_items_for_update = AsyncMock(return_value=[self.item])
        self.tasks.get_inventory_count_items_for_update = AsyncMock(return_value=[])
        self.tasks.save = AsyncMock(side_effect=lambda task: task)
        self.submissions = MagicMock()
        self.submissions.get_for_update = AsyncMock(return_value=self.submission)
        self.employees = MagicMock()
        self.employees.get_for_update = AsyncMock(return_value=self.executor)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.inventory = MagicMock()
        self.inventory.stock_out_in_transaction = AsyncMock()
        self.inventory.ship_reserved_in_transaction = AsyncMock()
        self.inventory.stock_in_in_transaction = AsyncMock()
        self.packing = MagicMock()
        self.packing.mark_packed_in_transaction = AsyncMock()
        self.receiving = MagicMock()
        self.receiving.receive_and_inspect_in_transaction = AsyncMock()
        self.buckets = MagicMock()
        self.buckets.move_in_transaction = AsyncMock()
        self.buckets.decrease_in_transaction = AsyncMock()
        self.picking = MagicMock()
        self.picking.pick_in_transaction = AsyncMock()
        self.reservation_service = MagicMock()
        self.reservation_service.mark_consumed_in_transaction = AsyncMock()
        self.reservations = MagicMock()
        self.reservations.get_for_update = AsyncMock()
        self.outbound = MagicMock()
        self.outbound.get_item = AsyncMock()
        self.outbound.get_for_update = AsyncMock()
        self.outbound.get_items_for_update = AsyncMock()
        self.outbound.save_item = AsyncMock(side_effect=lambda item: item)
        self.outbound.save_order = AsyncMock(side_effect=lambda order: order)
        self.inventory_count = MagicMock()
        self.inventory_count.record_counts_in_transaction = AsyncMock()
        self.service = CapabilityExecutionService(
            self.session,  # type: ignore[arg-type]
            self.executions,
            self.tasks,
            self.submissions,
            self.employees,
            self.audits,
            self.inventory,
            self.packing,
            self.receiving,
            self.buckets,
            self.picking,
            self.reservation_service,
            self.reservations,
            self.outbound,
            inventory_count_service=self.inventory_count,
        )

    async def test_execute_runs_capability_and_marks_execution_succeeded(self) -> None:
        result = await self.service.execute(execution_id=701)

        self.assertIs(result, self.execution)
        self.assertEqual(self.execution.status, ExecutionStatus.SUCCEEDED)
        self.assertEqual(self.execution.attempt_count, 1)
        self.assertIsNotNone(self.execution.started_at)
        self.assertIsNotNone(self.execution.completed_at)
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.assertEqual(self.task.reason, "实际出库40件")
        self.assertEqual(self.item.actual_quantity, Decimal("40"))
        self.inventory.stock_out_in_transaction.assert_awaited_once()
        inventory_call = self.inventory.stock_out_in_transaction.await_args
        self.assertEqual(inventory_call.args, (1, "WH-A", 40))
        self.assertEqual(inventory_call.kwargs["reference_id"], 1001)
        self.inventory.ship_reserved_in_transaction.assert_not_awaited()
        self.assertEqual(self.audits.append.await_count, 2)
        started = self.audits.append.await_args_list[0].args[0]
        completed = self.audits.append.await_args_list[1].args[0]
        self.assertEqual(started.action, "START_TASK_EXECUTION")
        self.assertEqual(completed.action, "COMPLETE_TASK_EXECUTION")
        self.assertEqual(started.trace_id, completed.trace_id)
        self.assertEqual(started.trace_id, inventory_call.kwargs["trace_id"])

    async def test_reservation_stock_out_consumes_picking_stock(self) -> None:
        self.task.source_type = "STOCK_RESERVATION"
        self.task.source_id = 2001
        self.item.planned_quantity = Decimal("40")
        self.item.source_bucket_id = 301
        self.item.from_location = WarehouseLocation(
            id=11,
            warehouse_id=1,
            code="SHIPPING-A",
            location_type=WarehouseLocationType.SHIPPING,
            is_active=True,
        )
        self.item.source_bucket = InventoryBucket(
            id=301,
            product_id=1,
            warehouse_code="WH-A",
            location_code="SHIPPING-A",
            lot_no="LOT-1",
            stock_status=StockStatus.PICKING,
            quantity=Decimal("40"),
        )
        reservation = StockReservation(
            id=2001,
            reservation_no="RSV-2001",
            outbound_order_item_id=401,
            product_id=1,
            warehouse_code="WH-A",
            location_code="SHIPPING-A",
            lot_no="LOT-1",
            quantity=Decimal("40"),
            status=ReservationStatus.ACTIVE,
        )
        outbound_item = OutboundOrderItem(
            id=401,
            outbound_order_id=501,
            product_id=1,
            requested_quantity=Decimal("40"),
            reserved_quantity=Decimal("40"),
            picked_quantity=Decimal("40"),
            shipped_quantity=Decimal("0"),
        )
        outbound_item.packed_at = datetime.now(timezone.utc)
        order = OutboundOrder(
            id=501,
            outbound_no="OUT-501",
            warehouse_code="WH-A",
            status=OutboundStatus.READY_TO_SHIP,
        )
        self.reservations.get_for_update.return_value = reservation
        self.outbound.get_item.return_value = outbound_item
        self.outbound.get_for_update.return_value = order
        self.outbound.get_items_for_update.return_value = [outbound_item]

        await self.service.execute(execution_id=701)

        self.buckets.decrease_in_transaction.assert_awaited_once()
        bucket_call = self.buckets.decrease_in_transaction.await_args
        self.assertEqual(bucket_call.args, (1, "WH-A", Decimal("40")))
        self.assertEqual(bucket_call.kwargs["stock_status"], StockStatus.PICKING)
        self.inventory.ship_reserved_in_transaction.assert_awaited_once()
        inventory_call = self.inventory.ship_reserved_in_transaction.await_args
        self.assertEqual(inventory_call.args, (1, "WH-A", Decimal("40")))
        self.assertEqual(inventory_call.kwargs["reference_type"], "STOCK_RESERVATION")
        self.assertEqual(inventory_call.kwargs["reference_id"], 2001)
        self.reservation_service.mark_consumed_in_transaction.assert_awaited_once()
        self.assertEqual(outbound_item.shipped_quantity, Decimal("40"))
        self.assertEqual(order.status, OutboundStatus.SHIPPED)
        self.assertIsNotNone(order.shipped_at)
        self.inventory.stock_out_in_transaction.assert_not_awaited()

    async def test_outbound_order_is_not_a_valid_reserved_stock_out_source(
        self,
    ) -> None:
        self.task.source_type = "OUTBOUND_ORDER"
        self.task.source_id = 501

        with self.assertRaisesRegex(
            InvalidTaskDataError,
            "must reference STOCK_RESERVATION",
        ):
            await self.service.execute(execution_id=701)

        self.inventory.stock_out_in_transaction.assert_not_awaited()
        self.inventory.ship_reserved_in_transaction.assert_not_awaited()
        self.buckets.decrease_in_transaction.assert_not_awaited()

    async def test_pack_completes_goods_task_without_changing_inventory(self) -> None:
        self.task.task_type = TaskType.PACK
        self.task.source_type = "OUTBOUND_ORDER_ITEM"
        self.task.source_id = 2001
        self.submission.form_data = {"remark": "包装完成"}
        self.execution.capability_name = TaskType.PACK.value

        await self.service.execute(execution_id=701)

        self.packing.mark_packed_in_transaction.assert_awaited_once()
        packing_call = self.packing.mark_packed_in_transaction.await_args
        self.assertEqual(packing_call.args, (2001,))
        self.assertIsNone(self.item.actual_quantity)
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.inventory.stock_out_in_transaction.assert_not_awaited()
        self.inventory.ship_reserved_in_transaction.assert_not_awaited()

    async def test_receive_completes_task_without_changing_inventory(self) -> None:
        self.task.task_type = TaskType.RECEIVE
        self.task.source_type = "INBOUND_RECEIPT_ITEM"
        self.task.source_id = 3001
        self.item.planned_quantity = Decimal("40")
        self.item.to_location_id = 11
        self.submission.form_data = {
            "received_quantity": "40.000",
            "accepted_quantity": "38.000",
            "defective_quantity": "2.000",
            "quarantined_quantity": "0.000",
            "rejected_quantity": "0.000",
            "remark": "两件破损",
        }
        self.execution.capability_name = TaskType.RECEIVE.value

        await self.service.execute(execution_id=701)

        self.receiving.receive_and_inspect_in_transaction.assert_awaited_once()
        receive_call = self.receiving.receive_and_inspect_in_transaction.await_args
        self.assertEqual(receive_call.args, (3001,))
        self.assertEqual(
            receive_call.kwargs["received_quantity"], Decimal("40.000")
        )
        self.assertEqual(receive_call.kwargs["accepted_quantity"], Decimal("38.000"))
        self.assertEqual(receive_call.kwargs["defective_quantity"], Decimal("2.000"))
        self.assertEqual(self.item.actual_quantity, Decimal("40.000"))
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.inventory.stock_in_in_transaction.assert_not_awaited()

    async def test_pick_moves_reserved_goods_without_shipping_inventory(self) -> None:
        self.task.task_type = TaskType.PICK
        self.task.source_type = "STOCK_RESERVATION"
        self.task.source_id = 401
        self.item.planned_quantity = Decimal("10")
        self.item.from_location_id = 11
        self.item.to_location_id = 12
        self.item.source_bucket_id = 501
        self.item.target_stock_status = StockStatus.PICKING
        self.item.from_location = WarehouseLocation(
            id=11,
            warehouse_id=1,
            code="STORAGE-A",
            location_type=WarehouseLocationType.STORAGE,
            is_active=True,
        )
        self.item.to_location = WarehouseLocation(
            id=12,
            warehouse_id=1,
            code="SHIPPING-A",
            location_type=WarehouseLocationType.SHIPPING,
            is_active=True,
        )
        self.item.source_bucket = InventoryBucket(
            id=501,
            product_id=1,
            warehouse_code="WH-A",
            location_code="STORAGE-A",
            lot_no="LOT-1",
            stock_status=StockStatus.RESERVED,
            quantity=Decimal("10"),
        )
        self.submission.form_data = {
            "actual_quantity": "10.000",
            "remark": "拣货完成",
        }
        self.execution.capability_name = TaskType.PICK.value

        await self.service.execute(execution_id=701)

        pick_call = self.picking.pick_in_transaction.await_args
        self.assertEqual(pick_call.args, (401,))
        self.assertEqual(pick_call.kwargs["to_location_code"], "SHIPPING-A")
        self.assertEqual(self.item.actual_quantity, Decimal("10.000"))
        self.inventory.stock_out_in_transaction.assert_not_awaited()
        self.inventory.ship_reserved_in_transaction.assert_not_awaited()

    async def test_inventory_count_records_results_without_adjusting_stock(
        self,
    ) -> None:
        count_item = InventoryCountItem(
            id=601,
            task_id=1001,
            product_id=1,
            location_id=11,
            system_quantity=Decimal("40.000"),
        )
        self.task.task_type = TaskType.INVENTORY_COUNT
        self.tasks.get_items_for_update.return_value = []
        self.tasks.get_inventory_count_items_for_update.return_value = [count_item]
        self.submission.form_data = {
            "results": [
                {
                    "inventory_count_item_id": 601,
                    "counted_quantity": "38.000",
                }
            ],
            "remark": "盘亏两件",
        }
        self.execution.capability_name = TaskType.INVENTORY_COUNT.value

        await self.service.execute(execution_id=701)

        count_call = self.inventory_count.record_counts_in_transaction.await_args
        self.assertEqual(count_call.args[0], [count_item])
        self.assertEqual(count_call.args[1], {601: Decimal("38.000")})
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.inventory.stock_in_in_transaction.assert_not_awaited()
        self.inventory.stock_out_in_transaction.assert_not_awaited()

    async def test_succeeded_execution_is_idempotent(self) -> None:
        await self.service.execute(execution_id=701)
        result = await self.service.execute(execution_id=701)

        self.assertIs(result, self.execution)
        self.inventory.stock_out_in_transaction.assert_awaited_once()
        self.assertEqual(self.execution.attempt_count, 1)
        self.assertEqual(self.audits.append.await_count, 2)

    async def test_running_execution_rejects_concurrent_call(self) -> None:
        self.execution.status = ExecutionStatus.RUNNING

        with self.assertRaises(TaskExecutionAlreadyRunningError):
            await self.service.execute(execution_id=701)

        self.inventory.stock_out_in_transaction.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_capability_failure_is_recorded_after_business_rollback(self) -> None:
        self.inventory.stock_out_in_transaction.side_effect = RuntimeError(
            "inventory unavailable"
        )

        with self.assertRaisesRegex(RuntimeError, "inventory unavailable"):
            await self.service.execute(execution_id=701)

        self.assertEqual(len(self.session.transactions), 2)
        self.assertIs(self.session.transactions[0].exception_type, RuntimeError)
        self.assertIsNone(self.session.transactions[1].exception_type)
        self.assertEqual(self.execution.status, ExecutionStatus.FAILED)
        self.assertEqual(self.execution.attempt_count, 1)
        self.assertEqual(self.execution.error_code, "RuntimeError")
        self.assertEqual(self.task.status, TaskStatus.EXECUTION_FAILED)
        self.assertIsNotNone(self.task.failed_at)
        self.assertEqual(
            self.audits.append.await_args.args[0].action,
            "FAIL_TASK_EXECUTION",
        )
        started = self.audits.append.await_args_list[0].args[0]
        failed = self.audits.append.await_args_list[-1].args[0]
        self.assertEqual(started.trace_id, failed.trace_id)

    async def test_unapproved_submission_cannot_execute(self) -> None:
        self.submission.status = SubmissionStatus.PENDING_REVIEW

        with self.assertRaises(InvalidTaskExecutionStateError):
            await self.service.execute(execution_id=701)

        self.inventory.stock_out_in_transaction.assert_not_awaited()
        self.assertEqual(len(self.session.transactions), 1)


if __name__ == "__main__":
    unittest.main()
