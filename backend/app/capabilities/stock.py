from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.services.inventory import InventoryService


class _StockPlan(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, str_strip_whitespace=True)

    product_id: int = Field(gt=0)
    warehouse_code: str = Field(min_length=1, max_length=64)
    quantity: int = Field(gt=0)


class _StockActual(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    quantity: int = Field(gt=0)


@dataclass(frozen=True)
class ValidatedStockTask:
    plan: _StockPlan
    actual: _StockActual

    @property
    def actual_data(self) -> dict[str, int]:
        return self.actual.model_dump()


class _StockCapability:
    def __init__(self, inventory_service: InventoryService) -> None:
        self._inventory = inventory_service

    def validate(
        self, planned_data: object, actual_data: object
    ) -> ValidatedStockTask:
        try:
            plan = _StockPlan.model_validate(planned_data)
            actual = _StockActual.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid stock task data") from None
        return ValidatedStockTask(plan=plan, actual=actual)


class StockInCapability(_StockCapability):
    async def execute(
        self, task: BusinessTask, employee: Employee, data: ValidatedStockTask
    ) -> None:
        await self._inventory.stock_in_in_transaction(
            data.plan.product_id,
            data.plan.warehouse_code,
            data.actual.quantity,
            reference_type="BUSINESS_TASK",
            reference_id=task.id,
            created_by=str(employee.id),
        )


class StockOutCapability(_StockCapability):
    async def execute(
        self, task: BusinessTask, employee: Employee, data: ValidatedStockTask
    ) -> None:
        await self._inventory.stock_out_in_transaction(
            data.plan.product_id,
            data.plan.warehouse_code,
            data.actual.quantity,
            reference_type="BUSINESS_TASK",
            reference_id=task.id,
            created_by=str(employee.id),
        )
