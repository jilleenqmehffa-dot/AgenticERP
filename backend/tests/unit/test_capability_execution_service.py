import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import (
    EmployeeStatus,
    ExecutionStatus,
    SubmissionStatus,
    TaskStatus,
    TaskType,
)
from app.core.exceptions import (
    InvalidTaskExecutionStateError,
    TaskExecutionAlreadyRunningError,
)
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.task_execution import TaskExecution
from app.models.task_submission import TaskSubmission
from app.models.warehouse import Warehouse
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
        self.tasks.save = AsyncMock(side_effect=lambda task: task)
        self.submissions = MagicMock()
        self.submissions.get_for_update = AsyncMock(return_value=self.submission)
        self.employees = MagicMock()
        self.employees.get_for_update = AsyncMock(return_value=self.executor)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.inventory = MagicMock()
        self.inventory.stock_out_in_transaction = AsyncMock()
        self.inventory.stock_in_in_transaction = AsyncMock()
        self.service = CapabilityExecutionService(
            self.session,  # type: ignore[arg-type]
            self.executions,
            self.tasks,
            self.submissions,
            self.employees,
            self.audits,
            self.inventory,
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
        self.assertEqual(self.audits.append.await_count, 2)
        started = self.audits.append.await_args_list[0].args[0]
        completed = self.audits.append.await_args_list[1].args[0]
        self.assertEqual(started.action, "START_TASK_EXECUTION")
        self.assertEqual(completed.action, "COMPLETE_TASK_EXECUTION")
        self.assertEqual(started.trace_id, completed.trace_id)
        self.assertEqual(started.trace_id, inventory_call.kwargs["trace_id"])

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
