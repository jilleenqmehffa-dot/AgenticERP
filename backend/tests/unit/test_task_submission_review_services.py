import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import EmployeeStatus, SubmissionStatus, TaskStatus, TaskType
from app.core.exceptions import (
    InvalidTaskDataError,
    InvalidTaskStateError,
    TaskReviewPermissionError,
)
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.role import Role
from app.models.task_submission import TaskSubmission
from app.models.warehouse import Warehouse
from app.services.task_review import TaskReviewService
from app.services.task_submission import TaskSubmissionService


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

    def in_transaction(self) -> bool:
        return self.active


def make_task(status: TaskStatus) -> BusinessTask:
    task = BusinessTask(
        id=1001,
        task_no="TASK-1001",
        task_type=TaskType.STOCK_OUT,
        status=status,
        warehouse_id=1,
        assignee_id=23,
    )
    task.warehouse = Warehouse(id=1, code="WH-A", name="Warehouse A")
    return task


class TaskSubmissionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.task = make_task(TaskStatus.IN_PROGRESS)
        self.employee = Employee(id=23, status=EmployeeStatus.ACTIVE)
        self.tasks = MagicMock()
        self.tasks.get_for_update = AsyncMock(return_value=self.task)
        self.tasks.save = AsyncMock(side_effect=lambda task: task)
        self.submissions = MagicMock()
        self.submissions.get_latest_for_update = AsyncMock(return_value=None)

        async def save_submission(submission: TaskSubmission) -> TaskSubmission:
            submission.id = submission.id or 501
            return submission

        self.submissions.save = AsyncMock(side_effect=save_submission)
        self.employees = MagicMock()
        self.employees.get_for_update = AsyncMock(return_value=self.employee)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.inventory = MagicMock()
        self.service = TaskSubmissionService(
            self.session,  # type: ignore[arg-type]
            self.tasks,
            self.submissions,
            self.employees,
            self.audits,
            self.inventory,
        )

    async def test_submit_saves_form_and_moves_task_to_pending_review(self) -> None:
        result = await self.service.submit(
            task_id=1001,
            submitted_by_user_id=23,
            form_data={
                "actual_quantity": 40,
                "remark": "实际出库40件",
            },
        )

        self.assertIs(result, self.task)
        self.assertEqual(self.task.status, TaskStatus.PENDING_REVIEW)
        submission = self.submissions.save.await_args.args[0]
        self.assertEqual(submission.version, 1)
        self.assertEqual(submission.status, SubmissionStatus.PENDING_REVIEW)
        self.assertEqual(submission.submitted_by_id, 23)
        self.assertEqual(submission.form_data["actual_quantity"], 40)
        self.assertEqual(submission.form_data["remark"], "实际出库40件")
        self.assertIsNotNone(submission.submitted_at)
        self.assertEqual(len(submission.payload_hash), 64)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "SUBMIT_TASK")
        self.assertEqual(audit.after_data["status"], "PENDING_REVIEW")
        self.assertEqual(self.session.begin_calls, 1)

    async def test_resubmission_increments_version(self) -> None:
        previous = TaskSubmission(
            task_id=1001,
            version=1,
            status=SubmissionStatus.CHANGES_REQUESTED,
            form_data={"actual_quantity": 30},
            payload_hash="different",
            submitted_by_id=23,
        )
        self.task.status = TaskStatus.CHANGES_REQUESTED
        self.submissions.get_latest_for_update.return_value = previous

        await self.service.submit(
            task_id=1001,
            submitted_by_user_id=23,
            form_data={"actual_quantity": 40},
        )

        self.assertEqual(self.submissions.save.await_args.args[0].version, 2)

    async def test_invalid_form_and_state_do_not_create_submission(self) -> None:
        with self.assertRaises(InvalidTaskDataError):
            await self.service.submit(
                task_id=1001,
                submitted_by_user_id=23,
                form_data={"actual_quantity": "40"},
            )

        self.task.status = TaskStatus.COMPLETED
        with self.assertRaises(InvalidTaskStateError):
            await self.service.submit(
                task_id=1001,
                submitted_by_user_id=23,
                form_data={"actual_quantity": 40},
            )

        self.submissions.save.assert_not_awaited()

    async def test_submission_audit_failure_aborts_transaction(self) -> None:
        self.audits.append.side_effect = RuntimeError("audit unavailable")

        with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
            await self.service.submit(
                task_id=1001,
                submitted_by_user_id=23,
                form_data={"actual_quantity": 40},
            )

        self.assertIs(self.session.transaction.exception_type, RuntimeError)
        self.submissions.save.assert_awaited_once()
        self.tasks.save.assert_awaited_once()


class TaskReviewServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.task = make_task(TaskStatus.PENDING_REVIEW)
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
            status=SubmissionStatus.PENDING_REVIEW,
            form_data={"actual_quantity": 40, "remark": "实际出库40件"},
            payload_hash="a" * 64,
            submitted_by_id=23,
        )
        self.executor = Employee(id=23, status=EmployeeStatus.ACTIVE)
        self.manager = Employee(id=99, status=EmployeeStatus.ACTIVE)
        self.manager.role = Role(id=2, code="MANAGER", name="Manager")
        self.tasks = MagicMock()
        self.tasks.get_for_update = AsyncMock(return_value=self.task)
        self.tasks.get_items_for_update = AsyncMock(return_value=[self.item])
        self.tasks.save = AsyncMock(side_effect=lambda task: task)
        self.submissions = MagicMock()
        self.submissions.get_pending_for_update = AsyncMock(
            return_value=self.submission
        )
        self.submissions.save = AsyncMock(side_effect=lambda submission: submission)
        self.employees = MagicMock()
        self.employees.get_with_role_for_update = AsyncMock(return_value=self.manager)
        self.employees.get_for_update = AsyncMock(return_value=self.executor)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.inventory = MagicMock()
        self.inventory.stock_out_in_transaction = AsyncMock()
        self.inventory.stock_in_in_transaction = AsyncMock()
        self.service = TaskReviewService(
            self.session,  # type: ignore[arg-type]
            self.tasks,
            self.submissions,
            self.employees,
            self.audits,
            self.inventory,
        )

    async def test_approve_executes_capability_and_completes_task(self) -> None:
        result = await self.service.approve(task_id=1001, reviewer_user_id=99)

        self.assertIs(result, self.task)
        self.assertEqual(self.submission.status, SubmissionStatus.APPROVED)
        self.assertEqual(self.submission.reviewed_by_id, 99)
        self.assertIsNotNone(self.submission.reviewed_at)
        self.assertEqual(self.task.status, TaskStatus.COMPLETED)
        self.assertEqual(self.task.reason, "实际出库40件")
        self.assertEqual(self.item.actual_quantity, Decimal("40"))
        self.inventory.stock_out_in_transaction.assert_awaited_once()
        call = self.inventory.stock_out_in_transaction.await_args
        self.assertEqual(call.args, (1, "WH-A", 40))
        self.assertEqual(call.kwargs["reference_id"], 1001)
        self.assertEqual(self.audits.append.await_count, 2)
        approval_audit = self.audits.append.await_args_list[0].args[0]
        completion_audit = self.audits.append.await_args_list[1].args[0]
        self.assertEqual(approval_audit.action, "APPROVE_TASK_SUBMISSION")
        self.assertEqual(completion_audit.action, "COMPLETE_APPROVED_TASK")
        self.assertEqual(approval_audit.trace_id, completion_audit.trace_id)
        self.assertEqual(
            approval_audit.trace_id,
            call.kwargs["trace_id"],
        )

    async def test_reject_requests_revision_without_executing_capability(self) -> None:
        result = await self.service.reject(
            task_id=1001,
            reviewer_user_id=99,
            reason="请重新核对数量",
        )

        self.assertIs(result, self.task)
        self.assertEqual(
            self.submission.status,
            SubmissionStatus.CHANGES_REQUESTED,
        )
        self.assertEqual(self.submission.review_reason, "请重新核对数量")
        self.assertEqual(self.task.status, TaskStatus.CHANGES_REQUESTED)
        self.assertEqual(self.task.reason, "请重新核对数量")
        self.inventory.stock_out_in_transaction.assert_not_awaited()
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "REJECT_TASK_SUBMISSION")

    async def test_non_manager_cannot_review(self) -> None:
        self.manager.role = Role(id=3, code="WAREHOUSE_OPERATOR", name="Operator")

        with self.assertRaises(TaskReviewPermissionError):
            await self.service.approve(task_id=1001, reviewer_user_id=99)

        self.submissions.save.assert_not_awaited()
        self.inventory.stock_out_in_transaction.assert_not_awaited()

    async def test_capability_failure_aborts_approval_transaction(self) -> None:
        self.inventory.stock_out_in_transaction.side_effect = RuntimeError(
            "inventory unavailable"
        )

        with self.assertRaisesRegex(RuntimeError, "inventory unavailable"):
            await self.service.approve(task_id=1001, reviewer_user_id=99)

        self.assertIs(self.session.transaction.exception_type, RuntimeError)
        self.assertEqual(self.audits.append.await_count, 1)
        self.assertEqual(
            self.audits.append.await_args.args[0].action,
            "APPROVE_TASK_SUBMISSION",
        )


if __name__ == "__main__":
    unittest.main()
