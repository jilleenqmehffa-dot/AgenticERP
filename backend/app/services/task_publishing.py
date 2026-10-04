from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    DispatchRequestStatus,
    EmployeeStatus,
    StockStatus,
    TaskStatus,
    TaskType,
    WarehouseLocationType,
)
from app.core.exceptions import InactiveEmployeeError, InvalidTaskDataError
from app.models.audit_log import AuditLog
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.putaway_dispatch import PutawayDispatchRepository
from app.repositories.warehouse_location import WarehouseLocationRepository


class TaskPublishingService:
    PUTAWAY_SOURCE_TYPE = "PUTAWAY_DISPATCH"
    _ROUTES = {
        StockStatus.PENDING_PUTAWAY: (
            WarehouseLocationType.STORAGE,
            StockStatus.AVAILABLE,
        ),
        StockStatus.DEFECTIVE: (
            WarehouseLocationType.QUARANTINE,
            StockStatus.DEFECTIVE,
        ),
        StockStatus.QUARANTINED: (
            WarehouseLocationType.QUARANTINE,
            StockStatus.QUARANTINED,
        ),
    }

    def __init__(
        self,
        session: AsyncSession,
        dispatch_repository: PutawayDispatchRepository | None = None,
        task_repository: BusinessTaskRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        location_repository: WarehouseLocationRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._dispatches = dispatch_repository or PutawayDispatchRepository(session)
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._employees = employee_repository or EmployeeRepository(session)
        self._locations = location_repository or WarehouseLocationRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def publish_putaway_request(
        self,
        request_id: int,
        assignee_id: int,
        to_location_id: int,
        publisher_type: ActorType,
        publisher_id: str | int | None,
        trace_id: str,
    ) -> BusinessTask:
        request_id = self._positive_id(request_id, "request_id")
        assignee_id = self._positive_id(assignee_id, "assignee_id")
        to_location_id = self._positive_id(to_location_id, "to_location_id")
        trace_id = self._required_text(trace_id, "trace_id")
        try:
            actor_type = ActorType(publisher_type)
        except (TypeError, ValueError):
            raise InvalidTaskDataError("publisher_type is invalid") from None

        async with self._session.begin():
            request = await self._dispatches.get_for_update(request_id)
            if request is None:
                raise InvalidTaskDataError(
                    f"putaway dispatch request does not exist: {request_id}"
                )
            if request.status == DispatchRequestStatus.PUBLISHED:
                if request.published_task is None:
                    raise InvalidTaskDataError(
                        "published dispatch request has no published task"
                    )
                return request.published_task
            if request.status != DispatchRequestStatus.PENDING:
                raise InvalidTaskDataError(
                    "putaway dispatch request is not pending"
                )

            source_bucket = request.source_bucket
            from_location = request.from_location
            expected_route = (
                self._ROUTES.get(source_bucket.stock_status)
                if source_bucket is not None
                else None
            )
            if (
                source_bucket is None
                or from_location is None
                or source_bucket.id != request.source_bucket_id
                or from_location.id != request.from_location_id
                or from_location.warehouse_id != request.warehouse_id
                or from_location.warehouse is None
                or from_location.location_type != WarehouseLocationType.RECEIVING
                or not from_location.is_active
                or source_bucket.location_code != from_location.code
                or source_bucket.warehouse_code != from_location.warehouse.code
                or expected_route
                != (
                    request.required_location_type,
                    request.target_stock_status,
                )
            ):
                raise InvalidTaskDataError(
                    "dispatch source bucket and receiving location are inconsistent"
                )

            assignee = await self._employees.get_for_update(assignee_id)
            if assignee is None or assignee.status != EmployeeStatus.ACTIVE:
                raise InactiveEmployeeError(assignee_id)
            target = await self._locations.get_for_update(to_location_id)
            if (
                target is None
                or not target.is_active
                or target.warehouse_id != request.warehouse_id
                or target.location_type != request.required_location_type
            ):
                raise InvalidTaskDataError(
                    "target location does not satisfy the dispatch request"
                )

            actor_id = await self._validate_publisher(actor_type, publisher_id)
            task = BusinessTask(
                task_no=f"PUTAWAY-{request.id}",
                task_type=TaskType.PUTAWAY,
                status=TaskStatus.ASSIGNED,
                warehouse_id=request.warehouse_id,
                assignee_id=assignee_id,
                source_type=self.PUTAWAY_SOURCE_TYPE,
                source_id=request.id,
                created_by_type=actor_type,
                created_by_id=actor_id,
            )
            task.items.append(
                BusinessTaskItem(
                    product_id=source_bucket.product_id,
                    from_location_id=request.from_location_id,
                    to_location_id=target.id,
                    source_bucket_id=request.source_bucket_id,
                    target_stock_status=request.target_stock_status,
                    planned_quantity=request.planned_quantity,
                )
            )
            await self._tasks.save(task)
            if task.id is None:
                raise RuntimeError("saved putaway task has no id")

            published_at = datetime.now(timezone.utc)
            request.status = DispatchRequestStatus.PUBLISHED
            request.published_task_id = task.id
            request.published_task = task
            request.published_by_type = actor_type
            request.published_by_id = actor_id
            request.published_at = published_at
            await self._dispatches.save(request)
            await self._audits.append(
                AuditLog(
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action="PUBLISH_PUTAWAY_TASK",
                    entity_type="PUTAWAY_DISPATCH_REQUEST",
                    entity_id=str(request.id),
                    before_data={"status": DispatchRequestStatus.PENDING.value},
                    after_data={
                        "status": DispatchRequestStatus.PUBLISHED.value,
                        "published_task_id": task.id,
                        "assignee_id": assignee_id,
                        "to_location_id": target.id,
                    },
                    trace_id=trace_id,
                    metadata_={"generation_key": request.generation_key},
                )
            )
            return task

    async def _validate_publisher(
        self,
        actor_type: ActorType,
        publisher_id: str | int | None,
    ) -> str:
        if actor_type == ActorType.AGENT:
            return self._required_text(publisher_id, "publisher_id")
        if actor_type == ActorType.EMPLOYEE:
            try:
                employee_id = int(publisher_id)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                raise InvalidTaskDataError(
                    "employee publisher_id must be a positive integer"
                ) from None
            employee_id = self._positive_id(employee_id, "publisher_id")
            publisher = await self._employees.get_with_role_for_update(employee_id)
            if (
                publisher is None
                or publisher.status != EmployeeStatus.ACTIVE
                or publisher.role is None
                or publisher.role.code != "MANAGER"
            ):
                raise InvalidTaskDataError(
                    "employee publisher must be an active MANAGER"
                )
            return str(employee_id)
        raise InvalidTaskDataError("SYSTEM cannot publish putaway tasks")

    @staticmethod
    def _positive_id(value: object, field: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidTaskDataError(f"{field} must be a positive integer")
        return value

    @staticmethod
    def _required_text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidTaskDataError(f"{field} must be a nonempty string")
        return value.strip()
