from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.stock import StockInCapability, StockOutCapability
from app.core.enums import ActorType, EmployeeStatus, TaskStatus, TaskType
from app.core.exceptions import (
    InactiveEmployeeError,
    InvalidTaskDataError,
    InvalidTaskStateError,
    TaskNotFoundError,
    TaskPermissionError,
    UnsupportedTaskTypeError,
)
from app.models.audit_log import AuditLog
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.employee import EmployeeRepository
from app.services.inventory import InventoryService


class TaskService:
    def __init__(
        self,
        session: AsyncSession,
        task_repository: BusinessTaskRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
        inventory_service: InventoryService | None = None,
    ) -> None:
        self._session = session
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._employees = employee_repository or EmployeeRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)
        inventory = inventory_service or InventoryService(session)
        self._capabilities = {
            TaskType.STOCK_IN: StockInCapability(inventory),
            TaskType.STOCK_OUT: StockOutCapability(inventory),
        }

    async def start_task(
        self,
        task_id: int,
        current_employee: Employee,
    ) -> BusinessTask:
        async with self._session.begin():
            task, employee = await self._get_authorized_task(
                task_id, current_employee, allowed_statuses={TaskStatus.PENDING}
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
                    before_status=TaskStatus.PENDING,
                    after_data={
                        "status": task.status.value,
                        "started_at": task.started_at.isoformat(),
                    },
                )
            )
        return task

    async def complete_task(
        self,
        task_id: int,
        current_employee: Employee,
        actual_data: dict[str, Any],
        reason: str | None = None,
    ) -> BusinessTask:
        async with self._session.begin():
            task, employee = await self._get_authorized_task(
                task_id,
                current_employee,
                allowed_statuses={TaskStatus.IN_PROGRESS},
            )
            task_reason = self._optional_reason(reason)
            capability = self._capabilities.get(task.task_type)
            if capability is None:
                raise UnsupportedTaskTypeError(task.task_type)
            items = await self._tasks.get_items_for_update(task.id)
            validated = capability.validate(task, items, actual_data)
            trace_id = str(uuid4())

            await capability.execute(task, employee, validated, trace_id)

            task.reason = task_reason
            task.status = TaskStatus.COMPLETED
            task.completed_at = datetime.now(timezone.utc)
            await self._tasks.save(task)
            await self._audits.append(
                self._audit_log(
                    task,
                    employee,
                    action="COMPLETE_TASK",
                    trace_id=trace_id,
                    before_status=TaskStatus.IN_PROGRESS,
                    after_data={
                        "status": task.status.value,
                        "items": [
                            {
                                "id": item.id,
                                "actual_quantity": str(item.actual_quantity),
                            }
                            for item in items
                        ],
                        "reason": task.reason,
                        "completed_at": task.completed_at.isoformat(),
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
        async with self._session.begin():
            task, employee = await self._get_authorized_task(
                task_id,
                current_employee,
                allowed_statuses={TaskStatus.PENDING, TaskStatus.IN_PROGRESS},
            )
            before_status = task.status
            cancel_reason = self._required_reason(reason)
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
    def _optional_reason(reason: str | None) -> str | None:
        if reason is None:
            return None
        return TaskService._required_reason(reason)

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
