from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.inventory_workflow import InventoryCountReviewDecision
from app.core.enums import (
    ActorType,
    AdjustmentStatus,
    EmployeeStatus,
    StockStatus,
    TaskStatus,
    TaskType,
)
from app.core.exceptions import (
    AdjustmentNotFoundError,
    AdjustmentReviewPermissionError,
    InvalidAdjustmentStateError,
    InvalidTaskDataError,
)
from app.core.validation import positive_int
from app.models.audit_log import AuditLog
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.models.inventory_adjustment import InventoryAdjustment
from app.models.inventory_count_item import InventoryCountItem
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.inventory_adjustment import InventoryAdjustmentRepository
from app.repositories.inventory_bucket import InventoryBucketRepository
from app.repositories.warehouse_location import WarehouseLocationRepository
from app.services.inventory.bucket import InventoryBucketService
from app.services.inventory.movement import InventoryMovementService


class InventoryCountWorkflow:
    """Task completion advances count -> review -> adjustment -> applied."""

    SOURCE_TYPE = "INVENTORY_ADJUSTMENT"

    def __init__(
        self,
        session: AsyncSession,
        *,
        adjustment_repository: InventoryAdjustmentRepository | None = None,
        task_repository: BusinessTaskRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        location_repository: WarehouseLocationRepository | None = None,
        inventory_repository: InventoryRepository | None = None,
        bucket_repository: InventoryBucketRepository | None = None,
        bucket_service: InventoryBucketService | None = None,
        movement_service: InventoryMovementService | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._adjustments = adjustment_repository or InventoryAdjustmentRepository(session)
        self._tasks = task_repository or BusinessTaskRepository(session)
        self._employees = employee_repository or EmployeeRepository(session)
        self._locations = location_repository or WarehouseLocationRepository(session)
        self._inventories = inventory_repository or InventoryRepository(session)
        self._bucket_rows = bucket_repository or InventoryBucketRepository(session)
        self._buckets = bucket_service or InventoryBucketService(session)
        self._movements = movement_service or InventoryMovementService(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def list_requests(
        self, *, reviewer_id: int, status: AdjustmentStatus
    ) -> list[InventoryAdjustment]:
        reviewer_id = positive_int(reviewer_id, "reviewer_id")
        if status not in {
            AdjustmentStatus.PENDING_REVIEW, AdjustmentStatus.READY_TO_ADJUST,
        }:
            raise InvalidAdjustmentStateError("unsupported task request status")
        async with self._session.begin():
            await self._reviewer(reviewer_id)
            return await self._adjustments.list_by_status(status)

    async def publish_review_task(
        self, *, adjustment_id: int, assignee_id: int, publisher_id: int
    ) -> BusinessTask:
        adjustment_id = positive_int(adjustment_id, "adjustment_id")
        assignee_id = positive_int(assignee_id, "assignee_id")
        publisher_id = positive_int(publisher_id, "publisher_id")
        async with self._session.begin():
            await self._reviewer(publisher_id)
            adjustment = await self._get(adjustment_id)
            if adjustment.review_task_id is not None:
                return await self._linked_task(adjustment.review_task_id)
            if adjustment.status != AdjustmentStatus.PENDING_REVIEW:
                raise InvalidAdjustmentStateError("review task request is not pending")
            _, count_task = await self._source(adjustment)
            reviewer = await self._reviewer(assignee_id)
            if reviewer.id == count_task.assignee_id:
                raise AdjustmentReviewPermissionError(
                    "counter cannot review own difference"
                )
            task = await self._tasks.save(
                BusinessTask(
                    task_no=f"COUNT-REVIEW-{adjustment.id}",
                    task_type=TaskType.INVENTORY_COUNT_REVIEW,
                    status=TaskStatus.ASSIGNED,
                    warehouse_id=count_task.warehouse_id,
                    assignee_id=reviewer.id,
                    source_type=self.SOURCE_TYPE,
                    source_id=adjustment.id,
                    created_by_type=ActorType.EMPLOYEE,
                    created_by_id=str(publisher_id),
                )
            )
            adjustment.review_task_id = task.id
            await self._adjustments.save(adjustment)
            await self._audits.append(
                self._audit(
                    adjustment, "PUBLISH_INVENTORY_REVIEW_TASK", str(uuid4()),
                    ActorType.EMPLOYEE, str(publisher_id),
                    AdjustmentStatus.PENDING_REVIEW, AdjustmentStatus.PENDING_REVIEW,
                )
            )
            return task

    async def publish_adjustment_task(
        self, *, adjustment_id: int, assignee_id: int, publisher_id: int
    ) -> BusinessTask:
        adjustment_id = positive_int(adjustment_id, "adjustment_id")
        assignee_id = positive_int(assignee_id, "assignee_id")
        publisher_id = positive_int(publisher_id, "publisher_id")
        async with self._session.begin():
            await self._reviewer(publisher_id)
            adjustment = await self._get(adjustment_id)
            if adjustment.adjustment_task_id is not None:
                return await self._linked_task(adjustment.adjustment_task_id)
            if adjustment.status != AdjustmentStatus.READY_TO_ADJUST:
                raise InvalidAdjustmentStateError("adjustment task request is not ready")
            _, count_task = await self._source(adjustment)
            assignee = await self._employees.get_for_update(assignee_id)
            if assignee is None or assignee.status != EmployeeStatus.ACTIVE:
                raise AdjustmentReviewPermissionError("adjustment assignee is inactive")
            task = await self._tasks.save(
                BusinessTask(
                    task_no=f"INVENTORY-ADJUST-{adjustment.id}",
                    task_type=TaskType.INVENTORY_ADJUSTMENT,
                    status=TaskStatus.ASSIGNED,
                    warehouse_id=count_task.warehouse_id,
                    assignee_id=assignee_id,
                    source_type=self.SOURCE_TYPE,
                    source_id=adjustment.id,
                    created_by_type=ActorType.EMPLOYEE,
                    created_by_id=str(publisher_id),
                )
            )
            adjustment.adjustment_task_id = task.id
            await self._adjustments.save(adjustment)
            await self._audits.append(
                self._audit(
                    adjustment, "PUBLISH_INVENTORY_ADJUSTMENT_TASK", str(uuid4()),
                    ActorType.EMPLOYEE, str(publisher_id),
                    AdjustmentStatus.READY_TO_ADJUST, AdjustmentStatus.READY_TO_ADJUST,
                )
            )
            return task

    async def after_task_completed_in_transaction(
        self,
        task: BusinessTask,
        items: list[InventoryCountItem],
        capability_result: object,
        *,
        trace_id: str,
    ) -> list[InventoryAdjustment]:
        if not self._session.in_transaction():
            raise RuntimeError("inventory count workflow requires an active transaction")
        if task.task_type == TaskType.INVENTORY_COUNT:
            return await self._after_count(task, items, trace_id)
        if task.task_type == TaskType.INVENTORY_COUNT_REVIEW:
            await self._after_review(task, capability_result, trace_id)
        elif task.task_type == TaskType.INVENTORY_ADJUSTMENT:
            await self._after_adjustment(task, trace_id)
        return []

    async def _after_count(
        self, task: BusinessTask, items: list[InventoryCountItem], trace_id: str
    ) -> list[InventoryAdjustment]:
        if task.status != TaskStatus.COMPLETED or task.warehouse is None or not items:
            raise InvalidTaskDataError("completed inventory count requires count items")
        requests = []
        for item in items:
            if item.task_id != task.id or item.counted_quantity is None:
                raise InvalidTaskDataError("inventory count item has no recorded result")
            difference = item.counted_quantity - item.system_quantity
            if difference == 0:
                continue
            existing = await self._adjustments.get_by_count_item_for_update(item.id)
            if existing is not None:
                if (
                    existing.product_id != item.product_id
                    or existing.warehouse_code != task.warehouse.code
                    or existing.location_id != item.location_id
                    or existing.system_quantity != item.system_quantity
                    or existing.counted_quantity != item.counted_quantity
                    or existing.difference_quantity != difference
                ):
                    raise InvalidTaskDataError(
                        "count item already has a different adjustment"
                    )
                requests.append(existing)
                continue
            adjustment = await self._adjustments.save(
                InventoryAdjustment(
                    count_item_id=item.id,
                    product_id=item.product_id,
                    warehouse_code=task.warehouse.code,
                    location_id=item.location_id,
                    system_quantity=item.system_quantity,
                    counted_quantity=item.counted_quantity,
                    difference_quantity=difference,
                    status=AdjustmentStatus.PENDING_REVIEW,
                )
            )
            await self._audits.append(
                self._audit(
                    adjustment, "REQUEST_INVENTORY_REVIEW_TASK", trace_id,
                    ActorType.SYSTEM, "INVENTORY_COUNT_WORKFLOW", None,
                    AdjustmentStatus.PENDING_REVIEW,
                )
            )
            requests.append(adjustment)
        return requests

    async def validate_review_task_in_transaction(
        self, task: BusinessTask, reviewer_id: int
    ) -> None:
        if not self._session.in_transaction():
            raise RuntimeError("inventory review requires an active transaction")
        adjustment = await self._task_adjustment(task, TaskType.INVENTORY_COUNT_REVIEW)
        if (
            adjustment.status != AdjustmentStatus.PENDING_REVIEW
            or adjustment.review_task_id != task.id
        ):
            raise InvalidAdjustmentStateError("review task does not match workflow state")
        reviewer = await self._reviewer(reviewer_id)
        _, count_task = await self._source(adjustment)
        if reviewer.id == count_task.assignee_id or reviewer.id != task.assignee_id:
            raise AdjustmentReviewPermissionError("reviewer is not allowed for this count")

    async def _after_review(
        self, task: BusinessTask, result: object, trace_id: str
    ) -> None:
        adjustment = await self._task_adjustment(task, TaskType.INVENTORY_COUNT_REVIEW)
        if (
            task.status != TaskStatus.COMPLETED
            or adjustment.status != AdjustmentStatus.PENDING_REVIEW
            or adjustment.review_task_id != task.id
            or not isinstance(result, InventoryCountReviewDecision)
            or result.reviewer_id != task.assignee_id
            or result.decision not in {"APPROVE", "REJECT"}
            or not result.reason.strip()
        ):
            raise InvalidAdjustmentStateError("review task completion is inconsistent")
        before = adjustment.status
        adjustment.status = (
            AdjustmentStatus.READY_TO_ADJUST
            if result.decision == "APPROVE" else AdjustmentStatus.REJECTED
        )
        adjustment.reviewed_by_id = result.reviewer_id
        adjustment.review_reason = result.reason
        adjustment.reviewed_at = datetime.now(timezone.utc)
        await self._adjustments.save(adjustment)
        await self._audits.append(
            self._audit(
                adjustment,
                "REQUEST_INVENTORY_ADJUSTMENT_TASK"
                if result.decision == "APPROVE" else "REJECT_INVENTORY_ADJUSTMENT",
                trace_id, ActorType.EMPLOYEE, str(result.reviewer_id),
                before, adjustment.status,
            )
        )

    async def apply_for_task_in_transaction(
        self, task: BusinessTask, *, employee_id: int, trace_id: str
    ) -> None:
        if not self._session.in_transaction():
            raise RuntimeError("inventory adjustment requires an active transaction")
        adjustment = await self._task_adjustment(task, TaskType.INVENTORY_ADJUSTMENT)
        if (
            adjustment.status != AdjustmentStatus.READY_TO_ADJUST
            or adjustment.adjustment_task_id != task.id
            or employee_id != task.assignee_id
        ):
            raise InvalidAdjustmentStateError("adjustment task does not match workflow state")
        _, count_task = await self._source(adjustment)
        location = await self._locations.get_for_update(adjustment.location_id)
        if (
            location is None or not location.is_active
            or location.warehouse_id != count_task.warehouse_id
        ):
            raise InvalidAdjustmentStateError("count location is unavailable")
        inventory = await self._inventories.get_for_update(
            adjustment.product_id, adjustment.warehouse_code
        )
        if inventory is None:
            raise InvalidAdjustmentStateError("warehouse inventory is unavailable")
        buckets = await self._bucket_rows.list_for_location_for_update(
            adjustment.product_id, adjustment.warehouse_code, location.code
        )
        active = [bucket for bucket in buckets if bucket.quantity > 0]
        if (
            len(active) > 1
            or (active and (
                active[0].lot_no != ""
                or active[0].stock_status != StockStatus.AVAILABLE
            ))
            or (active[0].quantity if active else Decimal(0))
            != adjustment.system_quantity
        ):
            raise InvalidAdjustmentStateError(
                "count baseline changed or contains multiple stock identities"
            )
        quantity = abs(adjustment.difference_quantity)
        actor_id = str(employee_id)
        bucket_args = dict(
            location_code=location.code, lot_no="", stock_status=StockStatus.AVAILABLE,
            actor_type=ActorType.EMPLOYEE, actor_id=actor_id, trace_id=trace_id,
        )
        movement_args = dict(
            reference_type="INVENTORY_ADJUSTMENT", reference_id=adjustment.id,
            created_by=actor_id, actor_type=ActorType.EMPLOYEE,
            actor_id=actor_id, trace_id=trace_id,
        )
        if adjustment.difference_quantity > 0:
            await self._movements.stock_in_in_transaction(
                adjustment.product_id, adjustment.warehouse_code, quantity,
                **movement_args,
            )
            await self._buckets.increase_in_transaction(
                adjustment.product_id, adjustment.warehouse_code, quantity,
                **bucket_args,
            )
        else:
            await self._movements.stock_out_in_transaction(
                adjustment.product_id, adjustment.warehouse_code, quantity,
                **movement_args,
            )
            await self._buckets.decrease_in_transaction(
                adjustment.product_id, adjustment.warehouse_code, quantity,
                **bucket_args,
            )

    async def _after_adjustment(self, task: BusinessTask, trace_id: str) -> None:
        adjustment = await self._task_adjustment(task, TaskType.INVENTORY_ADJUSTMENT)
        if (
            task.status != TaskStatus.COMPLETED
            or adjustment.status != AdjustmentStatus.READY_TO_ADJUST
            or adjustment.adjustment_task_id != task.id
        ):
            raise InvalidAdjustmentStateError("adjustment task completion is inconsistent")
        adjustment.status = AdjustmentStatus.APPLIED
        adjustment.applied_at = datetime.now(timezone.utc)
        await self._adjustments.save(adjustment)
        await self._audits.append(
            self._audit(
                adjustment, "COMPLETE_INVENTORY_ADJUSTMENT", trace_id,
                ActorType.EMPLOYEE, str(task.assignee_id),
                AdjustmentStatus.READY_TO_ADJUST, AdjustmentStatus.APPLIED,
            )
        )

    async def _task_adjustment(
        self, task: BusinessTask, expected_type: TaskType
    ) -> InventoryAdjustment:
        if (
            task.task_type != expected_type or task.source_type != self.SOURCE_TYPE
            or task.source_id is None
        ):
            raise InvalidTaskDataError("task does not reference an inventory adjustment")
        return await self._get(task.source_id)

    async def _linked_task(self, task_id: int) -> BusinessTask:
        task = await self._tasks.get_for_update(task_id)
        if task is None:
            raise InvalidAdjustmentStateError("published workflow task is missing")
        return task

    async def _get(self, adjustment_id: int) -> InventoryAdjustment:
        adjustment = await self._adjustments.get_for_update(adjustment_id)
        if adjustment is None:
            raise AdjustmentNotFoundError(adjustment_id)
        return adjustment

    async def _reviewer(self, reviewer_id: int) -> Employee:
        reviewer = await self._employees.get_with_role_for_update(reviewer_id)
        if (
            reviewer is None or reviewer.status != EmployeeStatus.ACTIVE
            or reviewer.role is None or reviewer.role.code != "MANAGER"
        ):
            raise AdjustmentReviewPermissionError(
                f"employee cannot review inventory adjustments: {reviewer_id}"
            )
        return reviewer

    async def _source(
        self, adjustment: InventoryAdjustment
    ) -> tuple[InventoryCountItem, BusinessTask]:
        item = await self._tasks.get_inventory_count_item_for_update(
            adjustment.count_item_id
        )
        if item is None:
            raise InvalidAdjustmentStateError("count item no longer exists")
        task = await self._tasks.get_for_update(item.task_id)
        if (
            task is None or task.task_type != TaskType.INVENTORY_COUNT
            or task.status != TaskStatus.COMPLETED or task.warehouse is None
            or task.warehouse.code != adjustment.warehouse_code
            or item.product_id != adjustment.product_id
            or item.location_id != adjustment.location_id
            or item.system_quantity != adjustment.system_quantity
            or item.counted_quantity != adjustment.counted_quantity
            or item.counted_quantity - item.system_quantity
            != adjustment.difference_quantity
        ):
            raise InvalidAdjustmentStateError("count source changed after recording")
        return item, task

    @staticmethod
    def _audit(
        adjustment: InventoryAdjustment, action: str, trace_id: str,
        actor_type: ActorType, actor_id: str,
        before: AdjustmentStatus | None, after: AdjustmentStatus,
    ) -> AuditLog:
        return AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="INVENTORY_ADJUSTMENT",
            entity_id=str(adjustment.id),
            before_data={"status": before.value if before else None},
            after_data={
                "status": after.value,
                "difference_quantity": str(adjustment.difference_quantity),
                "reviewed_by_id": adjustment.reviewed_by_id,
                "review_task_id": adjustment.review_task_id,
                "adjustment_task_id": adjustment.adjustment_task_id,
            },
            trace_id=trace_id,
            metadata_={
                "count_item_id": adjustment.count_item_id,
                "product_id": adjustment.product_id,
                "warehouse_code": adjustment.warehouse_code,
                "location_id": adjustment.location_id,
            },
        )
