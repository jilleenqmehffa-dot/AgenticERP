from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.dispatcher import CapabilityDispatcher
from app.core.enums import ActorType, EmployeeStatus, SubmissionStatus, TaskStatus
from app.core.exceptions import (
    InactiveEmployeeError,
    InvalidTaskDataError,
    InvalidTaskStateError,
    TaskNotFoundError,
    TaskPermissionError,
    TaskReviewPermissionError,
    TaskSubmissionNotFoundError,
)
from app.models.audit_log import AuditLog
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.models.task_submission import TaskSubmission
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.task_submission import TaskSubmissionRepository
from app.services.inventory import InventoryService
from app.services.task_submission import TaskSubmissionService


class TaskReviewService:
    def __init__(
        self,
        session: AsyncSession,
        task_repository: BusinessTaskRepository | None = None,
        submission_repository: TaskSubmissionRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
        inventory_service: InventoryService | None = None,
    ) -> None:
        self._session = session
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._submissions = submission_repository or TaskSubmissionRepository(session)
        self._employees = employee_repository or EmployeeRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)
        self._dispatcher = CapabilityDispatcher(
            inventory_service or InventoryService(session)
        )

    async def approve(
        self,
        *,
        task_id: int,
        reviewer_user_id: int,
    ) -> BusinessTask:
        task_id = self._positive_id(task_id, "task_id")
        reviewer_user_id = self._positive_id(
            reviewer_user_id, "reviewer_user_id"
        )

        async with self._session.begin():
            task, submission, reviewer = await self._get_review_context(
                task_id, reviewer_user_id
            )
            executor = await self._employees.get_for_update(submission.submitted_by_id)
            if executor is None or executor.status != EmployeeStatus.ACTIVE:
                raise InactiveEmployeeError(submission.submitted_by_id)
            if executor.id != task.assignee_id:
                raise TaskPermissionError(task.id)

            form = TaskSubmissionService.validate_stock_form(submission.form_data)
            now = datetime.now(timezone.utc)
            trace_id = str(uuid4())
            submission.status = SubmissionStatus.APPROVED
            submission.reviewed_by_id = reviewer.id
            submission.reviewed_at = now
            submission.review_reason = None
            await self._submissions.save(submission)

            task.status = TaskStatus.APPROVED_FOR_EXECUTION
            await self._tasks.save(task)
            await self._audits.append(
                self._review_audit(
                    task,
                    submission,
                    reviewer,
                    action="APPROVE_TASK_SUBMISSION",
                    trace_id=trace_id,
                    after_status=TaskStatus.APPROVED_FOR_EXECUTION,
                )
            )

            items = await self._tasks.get_items_for_update(task.id)
            await self._dispatcher.execute(
                task,
                executor,
                items,
                {"quantity": form["actual_quantity"]},
                trace_id,
            )

            task.reason = form.get("remark")
            task.status = TaskStatus.COMPLETED
            task.completed_at = now
            await self._tasks.save(task)
            await self._audits.append(
                AuditLog(
                    actor_type=ActorType.EMPLOYEE,
                    actor_id=str(reviewer.id),
                    action="COMPLETE_APPROVED_TASK",
                    entity_type="BUSINESS_TASK",
                    entity_id=str(task.id),
                    before_data={"status": TaskStatus.APPROVED_FOR_EXECUTION.value},
                    after_data={
                        "status": TaskStatus.COMPLETED.value,
                        "submission_version": submission.version,
                        "completed_at": task.completed_at.isoformat(),
                    },
                    trace_id=trace_id,
                    metadata_={},
                )
            )
        return task

    async def reject(
        self,
        *,
        task_id: int,
        reviewer_user_id: int,
        reason: str,
    ) -> BusinessTask:
        task_id = self._positive_id(task_id, "task_id")
        reviewer_user_id = self._positive_id(
            reviewer_user_id, "reviewer_user_id"
        )
        review_reason = self._required_reason(reason)

        async with self._session.begin():
            task, submission, reviewer = await self._get_review_context(
                task_id, reviewer_user_id
            )
            now = datetime.now(timezone.utc)
            trace_id = str(uuid4())
            submission.status = SubmissionStatus.CHANGES_REQUESTED
            submission.reviewed_by_id = reviewer.id
            submission.reviewed_at = now
            submission.review_reason = review_reason
            await self._submissions.save(submission)

            task.status = TaskStatus.CHANGES_REQUESTED
            task.reason = review_reason
            await self._tasks.save(task)
            await self._audits.append(
                self._review_audit(
                    task,
                    submission,
                    reviewer,
                    action="REJECT_TASK_SUBMISSION",
                    trace_id=trace_id,
                    after_status=TaskStatus.CHANGES_REQUESTED,
                    reason=review_reason,
                )
            )
        return task

    async def _get_review_context(
        self,
        task_id: int,
        reviewer_user_id: int,
    ) -> tuple[BusinessTask, TaskSubmission, Employee]:
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.status != TaskStatus.PENDING_REVIEW:
            raise InvalidTaskStateError(task_id)

        submission = await self._submissions.get_pending_for_update(task_id)
        if submission is None:
            raise TaskSubmissionNotFoundError(task_id)
        if submission.submitted_by_id == reviewer_user_id:
            raise TaskReviewPermissionError(reviewer_user_id)

        reviewer = await self._employees.get_with_role_for_update(reviewer_user_id)
        if reviewer is None or reviewer.status != EmployeeStatus.ACTIVE:
            raise InactiveEmployeeError(reviewer_user_id)
        if reviewer.role is None or reviewer.role.code != "MANAGER":
            raise TaskReviewPermissionError(reviewer_user_id)
        return task, submission, reviewer

    @staticmethod
    def _review_audit(
        task: BusinessTask,
        submission: TaskSubmission,
        reviewer: Employee,
        *,
        action: str,
        trace_id: str,
        after_status: TaskStatus,
        reason: str | None = None,
    ) -> AuditLog:
        return AuditLog(
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(reviewer.id),
            action=action,
            entity_type="TASK_SUBMISSION",
            entity_id=str(submission.id),
            before_data={"status": SubmissionStatus.PENDING_REVIEW.value},
            after_data={
                "status": submission.status.value,
                "task_status": after_status.value,
                "reason": reason,
            },
            trace_id=trace_id,
            metadata_={"task_id": task.id, "submission_version": submission.version},
        )

    @staticmethod
    def _required_reason(reason: object) -> str:
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidTaskDataError("review reason must be a nonempty string")
        return reason.strip()

    @staticmethod
    def _positive_id(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidTaskDataError(f"{field_name} must be a positive integer")
        return value
