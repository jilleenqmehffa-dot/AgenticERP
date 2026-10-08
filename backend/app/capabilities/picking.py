from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.contracts.task_execution import MovementTaskInput
from app.core.enums import ActorType, StockStatus, WarehouseLocationType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.services.outbound.picking import PickingService


@dataclass(frozen=True)
class ValidatedPickingTask:
    item: BusinessTaskItem
    quantity: Decimal


class PickCapability:
    _SOURCE_TYPE = "STOCK_RESERVATION"

    def __init__(self, picking_service: PickingService) -> None:
        self._picking = picking_service

    def validate(
        self,
        task: BusinessTask,
        items: list[BusinessTaskItem],
        actual_data: object,
    ) -> ValidatedPickingTask:
        try:
            actual = MovementTaskInput.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid picking task data") from None
        if task.source_type != self._SOURCE_TYPE or task.source_id is None:
            raise InvalidTaskDataError(
                "picking task must reference a stock reservation"
            )
        if len(items) != 1:
            raise InvalidTaskDataError("picking task must contain exactly one item")
        item = items[0]
        if (
            item.source_bucket is None
            or item.from_location is None
            or item.to_location is None
            or item.target_stock_status != StockStatus.PICKING
        ):
            raise InvalidTaskDataError(
                "picking task requires source bucket, locations and PICKING target status"
            )
        if actual.actual_quantity != item.planned_quantity:
            raise InvalidTaskDataError(
                "picking actual quantity must equal planned quantity"
            )
        source = item.source_bucket
        if (
            source.product_id != item.product_id
            or source.warehouse_code != task.warehouse.code
            or source.location_code != item.from_location.code
            or source.stock_status != StockStatus.RESERVED
            or item.from_location.warehouse_id != task.warehouse_id
            or item.to_location.warehouse_id != task.warehouse_id
            or item.to_location.location_type != WarehouseLocationType.SHIPPING
            or not item.from_location.is_active
            or not item.to_location.is_active
        ):
            raise InvalidTaskDataError("picking inventory route is invalid")
        return ValidatedPickingTask(item=item, quantity=actual.actual_quantity)

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedPickingTask,
        trace_id: str,
    ) -> None:
        item = data.item
        source = item.source_bucket
        assert source is not None
        assert item.to_location is not None
        assert task.source_id is not None
        await self._picking.pick_in_transaction(
            task.source_id,
            quantity=data.quantity,
            to_location_code=item.to_location.code,
            expected_product_id=item.product_id,
            expected_from_location_code=source.location_code,
            expected_lot_no=source.lot_no,
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
        item.actual_quantity = data.quantity
