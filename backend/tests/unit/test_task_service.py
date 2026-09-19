import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import (
    ActorType,
    EmployeeStatus,
    InventoryStatus,
    MovementType,
    TaskStatus,
    TaskType,
)
from app.core.exceptions import (
    InactiveEmployeeError,
    InsufficientStockError,
    InvalidTaskDataError,
    InvalidTaskStateError,
    TaskNotFoundError,
    TaskPermissionError,
)
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.models.inventory import Inventory
from app.services.inventory import InventoryService
from app.services.task import TaskService


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session
        self.exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeTransaction":
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
        self.transaction = FakeTransaction(self)
        self.begin_calls = 0
        self.active = False

    def begin(self) -> FakeTransaction:
        self.begin_calls += 1
        self.active = True
        return self.transaction

    def in_transaction(self) -> bool:
        return self.active


class TaskServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.employee = Employee(id=23, status=EmployeeStatus.ACTIVE)
        self.task = BusinessTask(
            id=1001,
            task_no="TASK-1001",
            task_type=TaskType.STOCK_OUT,
            status=TaskStatus.PENDING,
            assigned_employee_id=23,
            planned_data={"product_id": 1, "warehouse_code": "A", "quantity": 50},
            actual_data=None,
            exception_reason=None,
            cancel_reason=None,
            completed_at=None,
            cancelled_at=None,
        )
        self.inventory = Inventory(
            product_id=1,
            warehouse_code="A",
            on_hand_quantity=Decimal("100"),
            reserved_quantity=Decimal("0"),
            low_stock_threshold=Decimal("30"),
            status=InventoryStatus.NORMAL,
        )
        self.tasks = MagicMock()
        self.tasks.get_for_update = AsyncMock(return_value=self.task)
        self.tasks.save = AsyncMock(side_effect=lambda task: task)
        self.employees = MagicMock()
        self.employees.get_for_update = AsyncMock(return_value=self.employee)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.inventories = MagicMock()
        self.inventories.get_for_update = AsyncMock(return_value=self.inventory)
        self.inventories.save = AsyncMock(side_effect=lambda inventory: inventory)
        self.movements = MagicMock()
        self.movements.save = AsyncMock(side_effect=lambda movement: movement)
        inventory_service = InventoryService(
            self.session, self.inventories, self.movements  # type: ignore[arg-type]
        )
        self.service = TaskService(
            self.session,  # type: ignore[arg-type]
            self.tasks,
            self.employees,
            self.audits,
            inventory_service,
        )

    async def test_complete_stock_out_uses_actual_quantity_and_audits(self) -> None:
        result = await self.service.complete_task(
            1001, self.employee, {"quantity": 40}, "10 units damaged"
        )

        self.assertIs(result, self.task)
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.assertEqual(self.task.actual_data, {"quantity": 40})
        self.assertEqual(self.task.exception_reason, "10 units damaged")
        self.assertIsNotNone(self.task.completed_at)
        self.assertIsNone(self.task.cancelled_at)
        self.assertEqual(self.inventory.on_hand_quantity, Decimal("60"))
        movement = self.movements.save.await_args.args[0]
        self.assertEqual(movement.movement_type, MovementType.OUT)
        self.assertEqual(movement.quantity, Decimal("40"))
        self.assertEqual(movement.reference_type, "BUSINESS_TASK")
        self.assertEqual(movement.reference_id, 1001)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.actor_type, ActorType.EMPLOYEE)
        self.assertEqual(audit.actor_id, "23")
        self.assertEqual(audit.action, "COMPLETE_TASK")
        self.assertEqual(audit.after_data["actual_data"], {"quantity": 40})
        self.assertEqual(self.session.begin_calls, 1)
        self.assertIsNone(self.session.transaction.exception_type)

    async def test_complete_stock_in_uses_incoming_capability(self) -> None:
        self.task.task_type = TaskType.STOCK_IN

        await self.service.complete_task(1001, self.employee, {"quantity": 40})

        self.assertEqual(self.inventory.on_hand_quantity, Decimal("140"))
        self.assertEqual(
            self.movements.save.await_args.args[0].movement_type,
            MovementType.IN,
        )

    async def test_invalid_actual_data_never_reaches_inventory(self) -> None:
        for actual in ({}, {"quantity": 0}, {"quantity": "40"},
                       {"quantity": True}, {"quantity": 40, "product_id": 2}):
            with self.subTest(actual=actual):
                with self.assertRaises(InvalidTaskDataError):
                    await self.service.complete_task(1001, self.employee, actual)

        self.inventories.get_for_update.assert_not_awaited()
        self.tasks.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_invalid_plan_never_reaches_inventory(self) -> None:
        self.task.planned_data = {"warehouse_code": "A", "quantity": 50}

        with self.assertRaises(InvalidTaskDataError):
            await self.service.complete_task(1001, self.employee, {"quantity": 40})

        self.inventories.get_for_update.assert_not_awaited()
        self.tasks.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_insufficient_stock_leaves_task_pending(self) -> None:
        self.inventory.on_hand_quantity = Decimal("20")

        with self.assertRaises(InsufficientStockError):
            await self.service.complete_task(1001, self.employee, {"quantity": 40})

        self.assertEqual(self.task.status, TaskStatus.PENDING)
        self.tasks.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()
        self.assertIs(self.session.transaction.exception_type, InsufficientStockError)

    async def test_cancel_requires_reason_and_writes_audit(self) -> None:
        with self.assertRaises(InvalidTaskDataError):
            await self.service.cancel_task(1001, self.employee, "  ")

        result = await self.service.cancel_task(
            1001, self.employee, "  Cannot proceed  "
        )

        self.assertIs(result, self.task)
        self.assertEqual(self.task.status, TaskStatus.CANCELLED)
        self.assertEqual(self.task.cancel_reason, "Cannot proceed")
        self.assertIsNotNone(self.task.cancelled_at)
        self.assertIsNone(self.task.completed_at)
        self.inventories.get_for_update.assert_not_awaited()
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "CANCEL_TASK")
        self.assertEqual(audit.after_data["cancel_reason"], "Cannot proceed")

    async def test_missing_wrong_employee_inactive_and_finished_are_rejected(
        self,
    ) -> None:
        self.tasks.get_for_update.return_value = None
        with self.assertRaises(TaskNotFoundError):
            await self.service.complete_task(1001, self.employee, {"quantity": 40})

        self.tasks.get_for_update.return_value = self.task
        self.task.assigned_employee_id = 99
        with self.assertRaises(TaskPermissionError):
            await self.service.cancel_task(1001, self.employee, "reason")

        self.task.assigned_employee_id = 23
        self.employee.status = EmployeeStatus.INACTIVE
        with self.assertRaises(InactiveEmployeeError):
            await self.service.complete_task(1001, self.employee, {"quantity": 40})

        self.employee.status = EmployeeStatus.ACTIVE
        self.task.status = TaskStatus.COMPLETED
        with self.assertRaises(InvalidTaskStateError):
            await self.service.cancel_task(1001, self.employee, "reason")

        self.assertEqual(self.session.begin_calls, 4)
        self.inventories.get_for_update.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_audit_failure_aborts_shared_transaction(self) -> None:
        self.audits.append.side_effect = RuntimeError("audit unavailable")

        with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
            await self.service.complete_task(1001, self.employee, {"quantity": 40})

        self.assertIs(self.session.transaction.exception_type, RuntimeError)
        self.assertEqual(self.session.begin_calls, 1)
        self.movements.save.assert_awaited_once()

    async def test_inventory_transaction_entry_requires_outer_transaction(self) -> None:
        inventory_service = InventoryService(
            self.session, self.inventories, self.movements  # type: ignore[arg-type]
        )

        with self.assertRaisesRegex(RuntimeError, "active transaction"):
            await inventory_service.stock_out_in_transaction(1, "A", 1)

        self.inventories.get_for_update.assert_not_awaited()

    async def test_completed_and_cancelled_tasks_cannot_repeat_action(self) -> None:
        await self.service.complete_task(1001, self.employee, {"quantity": 40})
        with self.assertRaises(InvalidTaskStateError):
            await self.service.complete_task(1001, self.employee, {"quantity": 40})

        self.task.status = TaskStatus.PENDING
        self.task.actual_data = None
        self.task.exception_reason = None
        self.task.completed_at = None
        await self.service.cancel_task(1001, self.employee, "cannot proceed")
        with self.assertRaises(InvalidTaskStateError):
            await self.service.cancel_task(1001, self.employee, "again")


if __name__ == "__main__":
    unittest.main()
