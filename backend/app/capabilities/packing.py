from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.contracts.task_execution import PackTaskInput
from app.core.enums import ActorType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.services.outbound.packing import PackingService


@dataclass(frozen=True)
class ValidatedPackingTask:
    outbound_order_item_id: int


class PackingCapability:
    _SOURCE_TYPE = "OUTBOUND_ORDER_ITEM"

    def __init__(self, packing_service: PackingService) -> None:
        self._packing = packing_service

    def validate(
        self,
        task: BusinessTask,
        items: list[BusinessTaskItem],
        actual_data: object,
    ) -> ValidatedPackingTask:
        try:
            PackTaskInput.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid packing task data") from None
        if task.source_type != self._SOURCE_TYPE or task.source_id is None:
            raise InvalidTaskDataError(
                "packing task must reference an outbound order item"
            )
        if len(items) != 1:
            raise InvalidTaskDataError("packing task must contain exactly one item")
        return ValidatedPackingTask(
            outbound_order_item_id=task.source_id,
        )

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedPackingTask,
        trace_id: str,
    ) -> None:
        await self._packing.mark_packed_in_transaction(
            data.outbound_order_item_id,
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
