import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.contracts.inventory_workflow import InventoryCountReviewDecision
from app.core.enums import AdjustmentStatus, EmployeeStatus, StockStatus, TaskStatus, TaskType
from app.core.exceptions import AdjustmentReviewPermissionError, InvalidAdjustmentStateError
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.models.inventory import Inventory
from app.models.inventory_bucket import InventoryBucket
from app.models.inventory_count_item import InventoryCountItem
from app.models.role import Role
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation
from app.workflows.inventory_count import InventoryCountWorkflow


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class FakeSession:
    def in_transaction(self):
        return True

    def begin(self):
        return FakeTransaction()


class InventoryCountWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.count_task = BusinessTask(
            id=101, task_type=TaskType.INVENTORY_COUNT,
            status=TaskStatus.COMPLETED, warehouse_id=1, assignee_id=23,
        )
        self.count_task.warehouse = Warehouse(id=1, code="WH-A", name="Warehouse")
        self.item = InventoryCountItem(
            id=11, task_id=101, product_id=201, location_id=301,
            system_quantity=Decimal("10"), counted_quantity=Decimal("8"),
        )
        self.adjustments = MagicMock()
        self.adjustments.get_by_count_item_for_update = AsyncMock(return_value=None)
        self.adjustments.get_for_update = AsyncMock()
        self.adjustments.list_by_status = AsyncMock(return_value=[])

        async def save_adjustment(adjustment):
            adjustment.id = adjustment.id or 51
            return adjustment

        self.adjustments.save = AsyncMock(side_effect=save_adjustment)
        self.tasks = MagicMock()
        self.tasks.get_for_update = AsyncMock(return_value=self.count_task)
        self.tasks.get_inventory_count_item_for_update = AsyncMock(return_value=self.item)
        self.next_task_id = 200

        async def save_task(task):
            self.next_task_id += 1
            task.id = task.id or self.next_task_id
            return task

        self.tasks.save = AsyncMock(side_effect=save_task)
        reviewer = Employee(id=9, status=EmployeeStatus.ACTIVE)
        reviewer.role = Role(code="MANAGER", name="Manager")
        self.employees = MagicMock()
        self.employees.get_with_role_for_update = AsyncMock(return_value=reviewer)
        self.employees.get_for_update = AsyncMock(return_value=Employee(
            id=24, status=EmployeeStatus.ACTIVE
        ))
        self.locations = MagicMock()
        self.locations.get_for_update = AsyncMock(return_value=WarehouseLocation(
            id=301, warehouse_id=1, code="A-01", is_active=True,
        ))
        self.inventories = MagicMock()
        self.inventories.get_for_update = AsyncMock(return_value=Inventory(
            product_id=201, warehouse_code="WH-A", on_hand_quantity=Decimal("10"),
            reserved_quantity=Decimal("0"), low_stock_threshold=Decimal("0"),
        ))
        self.bucket_rows = MagicMock()
        self.bucket_rows.list_for_location_for_update = AsyncMock(return_value=[
            InventoryBucket(
                product_id=201, warehouse_code="WH-A", location_code="A-01",
                lot_no="", stock_status=StockStatus.AVAILABLE, quantity=Decimal("10"),
            )
        ])
        self.buckets = MagicMock()
        self.buckets.increase_in_transaction = AsyncMock()
        self.buckets.decrease_in_transaction = AsyncMock()
        self.movements = MagicMock()
        self.movements.stock_in_in_transaction = AsyncMock()
        self.movements.stock_out_in_transaction = AsyncMock()
        self.audits = MagicMock()
        self.audits.append = AsyncMock()
        self.workflow = InventoryCountWorkflow(
            FakeSession(),  # type: ignore[arg-type]
            adjustment_repository=self.adjustments,
            task_repository=self.tasks,
            employee_repository=self.employees,
            location_repository=self.locations,
            inventory_repository=self.inventories,
            bucket_repository=self.bucket_rows,
            bucket_service=self.buckets,
            movement_service=self.movements,
            audit_repository=self.audits,
        )

    async def _request(self):
        requests = await self.workflow.after_task_completed_in_transaction(
            self.count_task, [self.item], None, trace_id="count-trace"
        )
        self.assertEqual(len(requests), 1)
        self.adjustments.get_for_update.return_value = requests[0]
        return requests[0]

    async def _publish_review(self):
        adjustment = await self._request()
        task = await self.workflow.publish_review_task(
            adjustment_id=51, assignee_id=9, publisher_id=9
        )
        return adjustment, task

    async def _approve_review(self):
        adjustment, review_task = await self._publish_review()
        await self.workflow.validate_review_task_in_transaction(review_task, 9)
        review_task.status = TaskStatus.COMPLETED
        await self.workflow.after_task_completed_in_transaction(
            review_task, [], InventoryCountReviewDecision("APPROVE", "verified", 9),
            trace_id="review-trace",
        )
        return adjustment, review_task

    async def test_count_creates_review_request_without_stock_change(self) -> None:
        adjustment = await self._request()
        self.assertEqual(adjustment.status, AdjustmentStatus.PENDING_REVIEW)
        self.assertIsNone(adjustment.review_task_id)
        self.movements.stock_out_in_transaction.assert_not_awaited()
        self.adjustments.get_by_count_item_for_update.return_value = adjustment
        await self._request()
        self.adjustments.save.assert_awaited_once()

    async def test_zero_difference_ends_at_count_task(self) -> None:
        self.item.counted_quantity = self.item.system_quantity
        requests = await self.workflow.after_task_completed_in_transaction(
            self.count_task, [self.item], None, trace_id="count-trace"
        )
        self.assertEqual(requests, [])

    async def test_review_task_completion_creates_adjustment_task_request(self) -> None:
        adjustment, review_task = await self._approve_review()
        self.assertEqual(review_task.task_type, TaskType.INVENTORY_COUNT_REVIEW)
        self.assertEqual(adjustment.review_task_id, review_task.id)
        self.assertEqual(adjustment.status, AdjustmentStatus.READY_TO_ADJUST)
        self.assertIsNone(adjustment.adjustment_task_id)
        self.movements.stock_out_in_transaction.assert_not_awaited()

    async def test_adjustment_task_completion_applies_movement_and_finishes(self) -> None:
        adjustment, _ = await self._approve_review()
        task = await self.workflow.publish_adjustment_task(
            adjustment_id=51, assignee_id=24, publisher_id=9
        )
        self.assertEqual(task.task_type, TaskType.INVENTORY_ADJUSTMENT)
        await self.workflow.apply_for_task_in_transaction(
            task, employee_id=24, trace_id="adjust-trace"
        )
        self.assertEqual(adjustment.status, AdjustmentStatus.READY_TO_ADJUST)
        self.movements.stock_out_in_transaction.assert_awaited_once()
        self.buckets.decrease_in_transaction.assert_awaited_once()
        self.assertEqual(
            self.movements.stock_out_in_transaction.await_args.kwargs["reference_type"],
            "INVENTORY_ADJUSTMENT",
        )
        task.status = TaskStatus.COMPLETED
        await self.workflow.after_task_completed_in_transaction(
            task, [], None, trace_id="adjust-trace"
        )
        self.assertEqual(adjustment.status, AdjustmentStatus.APPLIED)

    async def test_stale_baseline_blocks_adjustment_task(self) -> None:
        adjustment, _ = await self._approve_review()
        task = await self.workflow.publish_adjustment_task(
            adjustment_id=51, assignee_id=24, publisher_id=9
        )
        self.bucket_rows.list_for_location_for_update.return_value[0].quantity = Decimal("9")
        with self.assertRaises(InvalidAdjustmentStateError):
            await self.workflow.apply_for_task_in_transaction(
                task, employee_id=24, trace_id="adjust-trace"
            )
        self.assertEqual(adjustment.status, AdjustmentStatus.READY_TO_ADJUST)
        self.movements.stock_out_in_transaction.assert_not_awaited()

    async def test_rejected_review_is_terminal(self) -> None:
        adjustment, review_task = await self._publish_review()
        review_task.status = TaskStatus.COMPLETED
        await self.workflow.after_task_completed_in_transaction(
            review_task, [], InventoryCountReviewDecision("REJECT", "recount", 9),
            trace_id="review-trace",
        )
        self.assertEqual(adjustment.status, AdjustmentStatus.REJECTED)
        with self.assertRaises(InvalidAdjustmentStateError):
            await self.workflow.publish_adjustment_task(
                adjustment_id=51, assignee_id=24, publisher_id=9
            )

    async def test_counter_cannot_be_review_task_assignee(self) -> None:
        await self._request()
        self.employees.get_with_role_for_update.return_value.id = 23
        with self.assertRaises(AdjustmentReviewPermissionError):
            await self.workflow.publish_review_task(
                adjustment_id=51, assignee_id=23, publisher_id=9
            )


if __name__ == "__main__":
    unittest.main()
