from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.exceptions import InvalidTaskDataError
from app.core.enums import ActorType
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.services.inventory import InventoryService


class _StockActual(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    quantity: int = Field(gt=0)


@dataclass(frozen=True)
class ValidatedStockTask:
    item: BusinessTaskItem
    actual: _StockActual


class _StockCapability:
    def __init__(self, inventory_service: InventoryService) -> None:
        self._inventory = inventory_service

    def validate(
        self,
        task: BusinessTask,
        items: list[BusinessTaskItem],
        actual_data: object,
    ) -> ValidatedStockTask:
        try:
            actual = _StockActual.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid stock task data") from None
        if len(items) != 1:
            raise InvalidTaskDataError("stock task must contain exactly one item")
        self._validate_locations(task, items[0])
        return ValidatedStockTask(item=items[0], actual=actual)

    @staticmethod
    def _validate_locations(task: BusinessTask, item: BusinessTaskItem) -> None:
        raise NotImplementedError


class StockInCapability(_StockCapability):
    @staticmethod
    def _validate_locations(task: BusinessTask, item: BusinessTaskItem) -> None:
        if item.to_location_id is None:
            raise InvalidTaskDataError("stock-in task requires to_location_id")

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedStockTask,
        trace_id: str,
    ) -> None:
        await self._inventory.stock_in_in_transaction(
            data.item.product_id,
            task.warehouse.code,
            data.actual.quantity,
            reference_type="BUSINESS_TASK",
            reference_id=task.id,
            created_by=str(employee.id),
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
        data.item.actual_quantity = data.actual.quantity


class StockOutCapability(_StockCapability):
    @staticmethod
    def _validate_locations(task: BusinessTask, item: BusinessTaskItem) -> None:
        if item.from_location_id is None:
            raise InvalidTaskDataError("stock-out task requires from_location_id")

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedStockTask,
        trace_id: str,
    ) -> None:
        await self._inventory.stock_out_in_transaction(
            data.item.product_id,
            task.warehouse.code,
            data.actual.quantity,
            reference_type="BUSINESS_TASK",
            reference_id=task.id,
            created_by=str(employee.id),
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
        data.item.actual_quantity = data.actual.quantity
