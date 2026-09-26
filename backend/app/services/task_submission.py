import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.dispatcher import CapabilityDispatcher
from app.core.enums import ActorType, EmployeeStatus, SubmissionStatus, TaskStatus
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
from app.models.task_submission import TaskSubmission
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.task_submission import TaskSubmissionRepository
from app.schemas.task_workflow import StockTaskSubmissionForm


class TaskSubmissionService:
    def __init__(
        self,
        session: AsyncSession,
        task_repository: BusinessTaskRepository | None = None,
        submission_repository: TaskSubmissionRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._submissions = submission_repository or TaskSubmissionRepository(session)
        self._employees = employee_repository or EmployeeRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def submit(
        self,
        *,
        task_id: int,
        submitted_by_user_id: int,
        form_data: dict[str, Any],
    ) -> BusinessTask:
        task_id = self._positive_id(task_id, "task_id")
        submitted_by_user_id = self._positive_id(
            submitted_by_user_id, "submitted_by_user_id"
        )

        async with self._session.begin():
            task = await self._tasks.get_for_update(task_id)
            if task is None:
                raise TaskNotFoundError(task_id)
            if task.status not in {
                TaskStatus.IN_PROGRESS,
                TaskStatus.CHANGES_REQUESTED,
            }:
                raise InvalidTaskStateError(task_id)
            if task.assignee_id != submitted_by_user_id:
                raise TaskPermissionError(task_id)

            employee = await self._employees.get_for_update(submitted_by_user_id)
            if employee is None or employee.status != EmployeeStatus.ACTIVE:
                raise InactiveEmployeeError(submitted_by_user_id)
            if not CapabilityDispatcher.supports(task.task_type):
                raise UnsupportedTaskTypeError(task.task_type)

            normalized_form = self.validate_stock_form(form_data)
            payload_hash = self._payload_hash(normalized_form)
            previous = await self._submissions.get_latest_for_update(task_id)
            if previous is not None and previous.payload_hash == payload_hash:
                raise InvalidTaskDataError("submission must differ from the previous version")

            submission = TaskSubmission(
                task_id=task.id,
                version=1 if previous is None else previous.version + 1,
                status=SubmissionStatus.PENDING_REVIEW,
                form_data=normalized_form,
                payload_hash=payload_hash,
                submitted_by_id=employee.id,
                submitted_at=datetime.now(timezone.utc),
            )
            await self._submissions.save(submission)

            before_status = task.status
            task.status = TaskStatus.PENDING_REVIEW
            await self._tasks.save(task)
            trace_id = str(uuid4())
            await self._audits.append(
                AuditLog(
                    actor_type=ActorType.EMPLOYEE,
                    actor_id=str(employee.id),
                    action="SUBMIT_TASK",
                    entity_type="BUSINESS_TASK",
                    entity_id=str(task.id),
                    before_data={"status": before_status.value},
                    after_data={
                        "status": task.status.value,
                        "submission_version": submission.version,
                    },
                    trace_id=trace_id,
                    metadata_={"payload_hash": payload_hash},
                )
            )
        return task

    @staticmethod
    def validate_stock_form(form_data: object) -> dict[str, Any]:
        try:
            form = StockTaskSubmissionForm.model_validate(form_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid stock task submission") from None
        return form.model_dump(mode="json", exclude_none=True)

    @staticmethod
    def _payload_hash(form_data: dict[str, Any]) -> str:
        canonical = json.dumps(
            form_data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _positive_id(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidTaskDataError(f"{field_name} must be a positive integer")
        return value
