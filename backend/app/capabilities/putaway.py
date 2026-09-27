from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.enums import ActorType, StockStatus, WarehouseLocationType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.services.inventory_bucket import InventoryBucketService
    from app.services.inventory_movement import InventoryMovementService


class _PutawayActual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)


@dataclass(frozen=True)
class ValidatedPutawayTask:
    item: BusinessTaskItem
    quantity: Decimal


class PutawayCapability:
    def __init__(
        self,
        bucket_service: InventoryBucketService,
        inventory_movement_service: InventoryMovementService,
    ) -> None:
        self._buckets = bucket_service
        self._inventory_movements = inventory_movement_service

    def validate(
        self,
        task: BusinessTask,
        items: list[BusinessTaskItem],
        actual_data: object,
    ) -> ValidatedPutawayTask:
        try:
            actual = _PutawayActual.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid putaway task data") from None
        if len(items) != 1:
            raise InvalidTaskDataError("putaway task must contain exactly one item")
        item = items[0]
        if (
            item.source_bucket is None
            or item.from_location is None
            or item.to_location is None
            or item.target_stock_status is None
        ):
            raise InvalidTaskDataError(
                "putaway task requires source bucket, source location, target location and target status"
            )
        quantity = actual.quantity
        if quantity != item.planned_quantity:
            raise InvalidTaskDataError(
                "putaway actual quantity must equal planned quantity"
            )
        source = item.source_bucket
        if (
            source.product_id != item.product_id
            or source.warehouse_code != task.warehouse.code
            or source.location_code != item.from_location.code
            or item.from_location.warehouse_id != task.warehouse_id
            or item.to_location.warehouse_id != task.warehouse_id
            or item.from_location.location_type != WarehouseLocationType.RECEIVING
            or not item.from_location.is_active
            or not item.to_location.is_active
        ):
            raise InvalidTaskDataError("putaway inventory identity is inconsistent")
        allowed_route = {
            (StockStatus.PENDING_PUTAWAY, StockStatus.AVAILABLE): (
                WarehouseLocationType.STORAGE
            ),
            (StockStatus.DEFECTIVE, StockStatus.DEFECTIVE): (
                WarehouseLocationType.QUARANTINE
            ),
            (StockStatus.QUARANTINED, StockStatus.QUARANTINED): (
                WarehouseLocationType.QUARANTINE
            ),
        }
        expected_location_type = allowed_route.get(
            (source.stock_status, item.target_stock_status)
        )
        if expected_location_type != item.to_location.location_type:
            raise InvalidTaskDataError("putaway quality route is invalid")
        return ValidatedPutawayTask(item=item, quantity=quantity)

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedPutawayTask,
        trace_id: str,
    ) -> None:
        item = data.item
        source = item.source_bucket
        assert source is not None
        assert item.to_location is not None
        assert item.target_stock_status is not None
        await self._buckets.move_in_transaction(
            item.product_id,
            task.warehouse.code,
            data.quantity,
            from_location_code=source.location_code,
            from_lot_no=source.lot_no,
            from_status=source.stock_status,
            to_location_code=item.to_location.code,
            to_lot_no=source.lot_no,
            to_status=item.target_stock_status,
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
        if item.target_stock_status == StockStatus.AVAILABLE:
            await self._inventory_movements.stock_in_in_transaction(
                item.product_id,
                task.warehouse.code,
                data.quantity,
                reference_type="BUSINESS_TASK",
                reference_id=task.id,
                created_by=str(employee.id),
                actor_type=ActorType.EMPLOYEE,
                actor_id=str(employee.id),
                trace_id=trace_id,
            )
        item.actual_quantity = data.quantity
