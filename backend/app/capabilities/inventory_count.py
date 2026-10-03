from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.enums import ActorType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.models.inventory_count_item import InventoryCountItem
    from app.services.inventory_count import InventoryCountService


class _InventoryCountResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_count_item_id: int = Field(gt=0)
    counted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)


class _InventoryCountActual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[_InventoryCountResult] = Field(min_length=1)
    remark: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_unique_items(self) -> "_InventoryCountActual":
        item_ids = [result.inventory_count_item_id for result in self.results]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("inventory count item ids must be unique")
        return self


@dataclass(frozen=True)
class ValidatedInventoryCountTask:
    items: list[InventoryCountItem]
    counts: dict[int, Decimal]


class InventoryCountCapability:
    def __init__(self, inventory_count_service: InventoryCountService) -> None:
        self._inventory_counts = inventory_count_service

    def validate(
        self,
        task: BusinessTask,
        items: list[InventoryCountItem],
        actual_data: object,
    ) -> ValidatedInventoryCountTask:
        try:
            actual = _InventoryCountActual.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid inventory count task data") from None
        if not items:
            raise InvalidTaskDataError(
                "inventory count task must contain at least one count item"
            )
        counts = {
            result.inventory_count_item_id: result.counted_quantity
            for result in actual.results
        }
        expected_ids = {item.id for item in items}
        if set(counts) != expected_ids:
            raise InvalidTaskDataError(
                "inventory count results must match all task count items"
            )
        return ValidatedInventoryCountTask(items=items, counts=counts)

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedInventoryCountTask,
        trace_id: str,
    ) -> None:
        await self._inventory_counts.record_counts_in_transaction(
            data.items,
            data.counts,
            warehouse_id=task.warehouse_id,
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
