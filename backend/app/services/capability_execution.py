from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.dispatcher import CapabilityDispatcher
from app.core.enums import (
    ActorType,
    EmployeeStatus,
    ExecutionStatus,
    SubmissionStatus,
    TaskStatus,
    TaskType,
)
from app.core.exceptions import (
    InactiveEmployeeError,
    InvalidTaskDataError,
    InvalidTaskExecutionStateError,
    InvalidTaskStateError,
    TaskExecutionAlreadyRunningError,
    TaskExecutionNotFoundError,
    TaskNotFoundError,
    TaskPermissionError,
    TaskSubmissionNotFoundError,
)
from app.models.audit_log import AuditLog
from app.models.task_execution import TaskExecution
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.outbound_order import OutboundOrderRepository
from app.repositories.stock_reservation import StockReservationRepository
from app.repositories.task_execution import TaskExecutionRepository
from app.repositories.task_submission import TaskSubmissionRepository
from app.services.inventory_balance import InventoryBalanceService
from app.services.inventory_bucket import InventoryBucketService
from app.services.inventory_count import InventoryCountService
from app.services.inventory_movement import InventoryMovementService
from app.services.packing import PackingService
from app.services.picking import PickingService
from app.services.receiving import ReceivingService
from app.services.reservation import ReservationService
from app.services.task_submission import TaskSubmissionService
from app.workflows.inbound import InboundWorkflow


class CapabilityExecutionService:
    def __init__(
        self,
        session: AsyncSession,
        execution_repository: TaskExecutionRepository | None = None,
        task_repository: BusinessTaskRepository | None = None,
        submission_repository: TaskSubmissionRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
        inventory_movement_service: InventoryMovementService | None = None,
        packing_service: PackingService | None = None,
        receiving_service: ReceivingService | None = None,
        bucket_service: InventoryBucketService | None = None,
        picking_service: PickingService | None = None,
        reservation_service: ReservationService | None = None,
        reservation_repository: StockReservationRepository | None = None,
        outbound_repository: OutboundOrderRepository | None = None,
        balance_service: InventoryBalanceService | None = None,
        inventory_count_service: InventoryCountService | None = None,
        inbound_workflow: InboundWorkflow | None = None,
    ) -> None:
        self._session = session
        self._executions = execution_repository or TaskExecutionRepository(session)
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._submissions = submission_repository or TaskSubmissionRepository(session)
        self._employees = employee_repository or EmployeeRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)
        balances = balance_service or InventoryBalanceService(session)
        inventory_movements = inventory_movement_service or InventoryMovementService(
            session,
            balance_service=balances,
        )
        buckets = bucket_service or InventoryBucketService(session)
        reservations = reservation_repository or StockReservationRepository(session)
        outbound = outbound_repository or OutboundOrderRepository(session)
        receiving = receiving_service or ReceivingService(session)
        self._inbound_workflow = inbound_workflow or InboundWorkflow(
            session,
            audit_repository=self._audits,
        )
        reservation = reservation_service or ReservationService(
            session,
            reservation_repository=reservations,
            outbound_repository=outbound,
            bucket_service=buckets,
            balance_service=balances,
        )
        self._dispatcher = CapabilityDispatcher(
            inventory_movements,
            packing_service or PackingService(session, outbound_repository=outbound),
            receiving,
            buckets,
            picking_service
            or PickingService(
                session,
                reservation_repository=reservations,
                outbound_repository=outbound,
                bucket_service=buckets,
            ),
            reservation,
            reservations,
            outbound,
            inventory_count_service
            or InventoryCountService(
                session,
                task_repository=self._tasks,
                audit_repository=self._audits,
            ),
        )

    async def execute(self, *, execution_id: int) -> TaskExecution:
        execution_id = self._positive_id(execution_id, "execution_id")
        execution_started = False
        attempt_trace_id: str | None = None
        try:
            async with self._session.begin():
                execution = await self._executions.get_for_update(execution_id)
                if execution is None:
                    raise TaskExecutionNotFoundError(execution_id)
                if execution.status == ExecutionStatus.SUCCEEDED:
                    return execution
                if execution.status == ExecutionStatus.RUNNING:
                    raise TaskExecutionAlreadyRunningError(execution_id)
                if execution.status not in {
                    ExecutionStatus.PENDING,
                    ExecutionStatus.FAILED,
                }:
                    raise InvalidTaskExecutionStateError(execution_id)

                task = await self._tasks.get_for_update(execution.task_id)
                if task is None:
                    raise TaskNotFoundError(execution.task_id)
                submission = await self._submissions.get_for_update(
                    execution.submission_id
                )
                if submission is None:
                    raise TaskSubmissionNotFoundError(task.id)
                if submission.task_id != task.id:
                    raise InvalidTaskDataError(
                        "execution submission does not belong to task"
                    )
                if submission.status != SubmissionStatus.APPROVED:
                    raise InvalidTaskExecutionStateError(execution_id)
                if execution.capability_name != task.task_type.value:
                    raise InvalidTaskDataError(
                        "execution capability does not match task type"
                    )
                if task.status not in {
                    TaskStatus.APPROVED_FOR_EXECUTION,
                    TaskStatus.EXECUTION_FAILED,
                }:
                    raise InvalidTaskStateError(task.id)

                executor = await self._employees.get_for_update(
                    submission.submitted_by_id
                )
                if executor is None or executor.status != EmployeeStatus.ACTIVE:
                    raise InactiveEmployeeError(submission.submitted_by_id)
                if executor.id != task.assignee_id:
                    raise TaskPermissionError(task.id)

                form = TaskSubmissionService.validate_form(
                    task.task_type,
                    submission.form_data,
                )
                attempt_trace_id = str(uuid4())
                previous_execution_status = execution.status
                started_at = datetime.now(timezone.utc)
                execution.status = ExecutionStatus.RUNNING
                execution.started_at = started_at
                execution.completed_at = None
                execution.error_code = None
                execution.error_message = None
                task.status = TaskStatus.EXECUTING
                task.failed_at = None
                await self._executions.save(execution)
                await self._tasks.save(task)
                await self._audits.append(
                    self._execution_audit(
                        execution,
                        action="START_TASK_EXECUTION",
                        trace_id=attempt_trace_id,
                        before_status=previous_execution_status,
                        after_status=ExecutionStatus.RUNNING,
                    )
                )
                execution_started = True

                items = await self._tasks.get_items_for_update(task.id)
                inventory_count_items = (
                    await self._tasks.get_inventory_count_items_for_update(task.id)
                    if task.task_type == TaskType.INVENTORY_COUNT
                    else []
                )
                actual_data = (
                    {}
                    if task.task_type == TaskType.PACK
                    else (
                        form
                        if task.task_type
                        in {TaskType.RECEIVE, TaskType.INVENTORY_COUNT}
                        else {"quantity": form["actual_quantity"]}
                    )
                )
                capability_result = await self._dispatcher.execute(
                    task,
                    executor,
                    items,
                    actual_data,
                    attempt_trace_id,
                    inventory_count_items,
                )

                completed_at = datetime.now(timezone.utc)
                execution.status = ExecutionStatus.SUCCEEDED
                execution.attempt_count += 1
                execution.completed_at = completed_at
                task.reason = form.get("remark")
                task.status = TaskStatus.COMPLETED
                task.completed_at = completed_at
                await self._executions.save(execution)
                await self._tasks.save(task)
                await self._inbound_workflow.after_task_completed_in_transaction(
                    task,
                    capability_result,
                    trace_id=attempt_trace_id,
                )
                await self._audits.append(
                    self._execution_audit(
                        execution,
                        action="COMPLETE_TASK_EXECUTION",
                        trace_id=attempt_trace_id,
                        before_status=ExecutionStatus.RUNNING,
                        after_status=ExecutionStatus.SUCCEEDED,
                    )
                )
            return execution
        except Exception as error:
            if execution_started:
                await self._record_failure(
                    execution_id,
                    error,
                    trace_id=attempt_trace_id or str(uuid4()),
                )
            raise

    async def _record_failure(
        self,
        execution_id: int,
        error: Exception,
        *,
        trace_id: str,
    ) -> None:
        async with self._session.begin():
            execution = await self._executions.get_for_update(execution_id)
            if execution is None or execution.status == ExecutionStatus.SUCCEEDED:
                return
            task = await self._tasks.get_for_update(execution.task_id)
            if task is None:
                raise TaskNotFoundError(execution.task_id)

            now = datetime.now(timezone.utc)
            execution.status = ExecutionStatus.FAILED
            execution.attempt_count += 1
            execution.started_at = execution.started_at or now
            execution.completed_at = now
            execution.error_code = type(error).__name__[:100]
            execution.error_message = str(error)[:2000]
            task.status = TaskStatus.EXECUTION_FAILED
            task.failed_at = now
            await self._executions.save(execution)
            await self._tasks.save(task)
            await self._audits.append(
                self._execution_audit(
                    execution,
                    action="FAIL_TASK_EXECUTION",
                    trace_id=trace_id,
                    before_status=ExecutionStatus.RUNNING,
                    after_status=ExecutionStatus.FAILED,
                    error_code=execution.error_code,
                )
            )

    @staticmethod
    def _execution_audit(
        execution: TaskExecution,
        *,
        action: str,
        trace_id: str,
        before_status: ExecutionStatus,
        after_status: ExecutionStatus,
        error_code: str | None = None,
    ) -> AuditLog:
        return AuditLog(
            actor_type=ActorType.SYSTEM,
            actor_id="SYSTEM",
            action=action,
            entity_type="TASK_EXECUTION",
            entity_id=str(execution.id),
            before_data={"status": before_status.value},
            after_data={
                "status": after_status.value,
                "attempt_count": execution.attempt_count,
                "error_code": error_code,
            },
            trace_id=trace_id,
            metadata_={
                "task_id": execution.task_id,
                "submission_id": execution.submission_id,
                "capability_name": execution.capability_name,
                "idempotency_key": execution.idempotency_key,
            },
        )

    @staticmethod
    def _positive_id(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidTaskDataError(f"{field_name} must be a positive integer")
        return value
