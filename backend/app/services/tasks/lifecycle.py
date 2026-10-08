from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, EmployeeStatus, TaskStatus
from app.core.exceptions import (
    InactiveEmployeeError,
    InvalidTaskDataError,
    InvalidTaskStateError,
    TaskNotFoundError,
    TaskPermissionError,
)
from app.core.validation import positive_int
from app.models.audit_log import AuditLog
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.employee import EmployeeRepository


class TaskLifecycleService:
    def __init__(
        self,
        session: AsyncSession,
        task_repository: BusinessTaskRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._employees = employee_repository or EmployeeRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def start_task(
        self,
        task_id: int,
        current_employee: Employee,
    ) -> BusinessTask:
        task_id = self._validate_task_id(task_id)
        self._validate_current_employee(current_employee)
        async with self._session.begin():
            task, employee = await self._get_authorized_task(
                task_id, current_employee, allowed_statuses={TaskStatus.ASSIGNED}
            )
            trace_id = str(uuid4())
            task.status = TaskStatus.IN_PROGRESS
            task.started_at = datetime.now(timezone.utc)
            await self._tasks.save(task)
            await self._audits.append(
                self._audit_log(
                    task,
                    employee,
                    action="START_TASK",
                    trace_id=trace_id,
                    before_status=TaskStatus.ASSIGNED,
                    after_data={
                        "status": task.status.value,
                        "started_at": task.started_at.isoformat(),
                    },
                )
            )
        return task

    async def cancel_task(
        self,
        task_id: int,
        current_employee: Employee,
        reason: str,
    ) -> BusinessTask:
        task_id = self._validate_task_id(task_id)
        self._validate_current_employee(current_employee)
        cancel_reason = self._required_reason(reason)
        async with self._session.begin():
            task, employee = await self._get_authorized_task(
                task_id,
                current_employee,
                allowed_statuses={
                    TaskStatus.ASSIGNED,
                    TaskStatus.IN_PROGRESS,
                    TaskStatus.CHANGES_REQUESTED,
                },
            )
            before_status = task.status
            trace_id = str(uuid4())
            task.status = TaskStatus.CANCELLED
            task.reason = cancel_reason
            task.cancelled_at = datetime.now(timezone.utc)
            await self._tasks.save(task)
            await self._audits.append(
                self._audit_log(
                    task,
                    employee,
                    action="CANCEL_TASK",
                    trace_id=trace_id,
                    before_status=before_status,
                    after_data={
                        "status": task.status.value,
                        "reason": task.reason,
                        "cancelled_at": task.cancelled_at.isoformat(),
                    },
                )
            )
        return task

    async def _get_authorized_task(
        self,
        task_id: int,
        current_employee: Employee,
        *,
        allowed_statuses: set[TaskStatus],
    ) -> tuple[BusinessTask, Employee]:
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise TaskNotFoundError(task_id)
        if task.assignee_id != current_employee.id:
            raise TaskPermissionError(task_id)
        employee = await self._employees.get_for_update(current_employee.id)
        if employee is None or employee.status != EmployeeStatus.ACTIVE:
            raise InactiveEmployeeError(current_employee.id)
        if task.status not in allowed_statuses:
            raise InvalidTaskStateError(task_id)
        return task, employee

    @staticmethod
    def _validate_task_id(task_id: object) -> int:
        return positive_int(task_id, "task_id", error=InvalidTaskDataError)

    @staticmethod
    def _validate_current_employee(employee: object) -> None:
        employee_id = getattr(employee, "id", None)
        if (
            isinstance(employee_id, bool)
            or not isinstance(employee_id, int)
            or employee_id <= 0
        ):
            raise InvalidTaskDataError("current employee must have a positive id")

    @staticmethod
    def _required_reason(reason: str) -> str:
        if not isinstance(reason, str) or not reason.strip():
            raise InvalidTaskDataError("reason must be a nonempty string")
        return reason.strip()

    @staticmethod
    def _audit_log(
        task: BusinessTask,
        employee: Employee,
        *,
        action: str,
        trace_id: str,
        before_status: TaskStatus,
        after_data: dict[str, Any],
    ) -> AuditLog:
        return AuditLog(
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            action=action,
            entity_type="BUSINESS_TASK",
            entity_id=str(task.id),
            before_data={"status": before_status.value},
            after_data=after_data,
            trace_id=trace_id,
            metadata_={},
        )
