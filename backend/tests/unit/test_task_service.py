import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import EmployeeStatus, TaskStatus, TaskType
from app.core.exceptions import (
    InactiveEmployeeError,
    InvalidTaskDataError,
    InvalidTaskStateError,
    TaskNotFoundError,
    TaskPermissionError,
)
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.services.task import TaskService


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
        self.transaction = FakeTransaction(self)
        self.begin_calls = 0
        self.active = False

    def begin(self) -> FakeTransaction:
        self.begin_calls += 1
        return self.transaction

class TaskServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.employee = Employee(id=23, status=EmployeeStatus.ACTIVE)
        self.task = BusinessTask(
            id=1001,
            task_no="TASK-1001",
            task_type=TaskType.STOCK_OUT,
            status=TaskStatus.ASSIGNED,
            warehouse_id=1,
            assignee_id=23,
            reason=None,
        )
        self.tasks = MagicMock()
        self.tasks.get_for_update = AsyncMock(return_value=self.task)

        self.tasks.save = AsyncMock(side_effect=lambda task: task)
        self.employees = MagicMock()
        self.employees.get_for_update = AsyncMock(return_value=self.employee)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = TaskService(
            self.session,  # type: ignore[arg-type]
            self.tasks,
            self.employees,
            self.audits,
        )

    async def test_start_task_moves_assigned_task_to_in_progress(self) -> None:
        result = await self.service.start_task(1001, self.employee)

        self.assertIs(result, self.task)
        self.assertEqual(self.task.status, TaskStatus.IN_PROGRESS)
        self.assertIsNotNone(self.task.started_at)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "START_TASK")
        self.assertEqual(audit.before_data, {"status": "ASSIGNED"})
        self.assertEqual(audit.after_data["status"], "IN_PROGRESS")

    async def test_cancel_requires_reason_and_writes_audit(self) -> None:
        self.task.status = TaskStatus.IN_PROGRESS

        with self.assertRaises(InvalidTaskDataError):
            await self.service.cancel_task(1001, self.employee, "  ")

        result = await self.service.cancel_task(
            1001,
            self.employee,
            "  Cannot proceed  ",
        )

        self.assertIs(result, self.task)
        self.assertEqual(self.task.status, TaskStatus.CANCELLED)
        self.assertEqual(self.task.reason, "Cannot proceed")
        self.assertIsNotNone(self.task.cancelled_at)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "CANCEL_TASK")

    async def test_missing_wrong_employee_inactive_and_finished_are_rejected(
        self,
    ) -> None:
        self.tasks.get_for_update.return_value = None
        with self.assertRaises(TaskNotFoundError):
            await self.service.start_task(1001, self.employee)

        self.tasks.get_for_update.return_value = self.task
        self.task.assignee_id = 99
        with self.assertRaises(TaskPermissionError):
            await self.service.cancel_task(1001, self.employee, "reason")

        self.task.assignee_id = 23
        self.employee.status = EmployeeStatus.INACTIVE
        with self.assertRaises(InactiveEmployeeError):
            await self.service.start_task(1001, self.employee)

        self.employee.status = EmployeeStatus.ACTIVE
        self.task.status = TaskStatus.COMPLETED
        with self.assertRaises(InvalidTaskStateError):
            await self.service.cancel_task(1001, self.employee, "reason")

    async def test_audit_failure_aborts_task_transaction(self) -> None:
        self.audits.append.side_effect = RuntimeError("audit unavailable")

        with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
            await self.service.start_task(1001, self.employee)

        self.assertIs(self.session.transaction.exception_type, RuntimeError)
        self.tasks.save.assert_awaited_once()

    async def test_invalid_task_identity_is_rejected_before_transaction(self) -> None:
        with self.assertRaises(InvalidTaskDataError):
            await self.service.start_task(0, self.employee)

        invalid_employee = Employee(id=0, status=EmployeeStatus.ACTIVE)
        with self.assertRaises(InvalidTaskDataError):
            await self.service.start_task(1001, invalid_employee)

        self.assertEqual(self.session.begin_calls, 0)
        self.tasks.get_for_update.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
