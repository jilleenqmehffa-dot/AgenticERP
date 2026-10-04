from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.enums import ActorType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.services.receiving import ReceivingResult, ReceivingService


class _ReceivingActual(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    accepted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    defective_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    quarantined_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    rejected_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    lot_no: str = Field(default="", max_length=100)
    remark: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_quality_total(self) -> "_ReceivingActual":
        quality_total = (
            self.accepted_quantity
            + self.defective_quantity
            + self.quarantined_quantity
            + self.rejected_quantity
        )
        if quality_total != self.received_quantity:
            raise ValueError("quality quantities must equal received_quantity")
        return self


@dataclass(frozen=True)
class ValidatedReceivingTask:
    item: BusinessTaskItem
    inbound_receipt_item_id: int
    actual: _ReceivingActual


class ReceiveCapability:
    _SOURCE_TYPE = "INBOUND_RECEIPT_ITEM"

    def __init__(self, receiving_service: ReceivingService) -> None:
        self._receiving = receiving_service

    def validate(
        self,
        task: BusinessTask,
        items: list[BusinessTaskItem],
        actual_data: object,
    ) -> ValidatedReceivingTask:
        try:
            actual = _ReceivingActual.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid receiving task data") from None
        if task.source_type != self._SOURCE_TYPE or task.source_id is None:
            raise InvalidTaskDataError(
                "receiving task must reference an inbound receipt item"
            )
        if len(items) != 1:
            raise InvalidTaskDataError("receiving task must contain exactly one item")
        item = items[0]
        if item.to_location_id is None:
            raise InvalidTaskDataError(
                "receiving task requires a receiving to_location_id"
            )
        if actual.received_quantity != item.planned_quantity:
            raise InvalidTaskDataError(
                "received quantity must equal the task planned quantity"
            )
        return ValidatedReceivingTask(
            item=item,
            inbound_receipt_item_id=task.source_id,
            actual=actual,
        )

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedReceivingTask,
        trace_id: str,
    ) -> ReceivingResult:
        if task.id is None or task.warehouse is None:
            raise InvalidTaskDataError("receiving task must be persisted with warehouse")
        result = await self._receiving.receive_and_inspect_in_transaction(
            data.inbound_receipt_item_id,
            received_quantity=data.actual.received_quantity,
            accepted_quantity=data.actual.accepted_quantity,
            defective_quantity=data.actual.defective_quantity,
            quarantined_quantity=data.actual.quarantined_quantity,
            rejected_quantity=data.actual.rejected_quantity,
            expected_product_id=data.item.product_id,
            business_task_id=task.id,
            warehouse_id=task.warehouse_id,
            warehouse_code=task.warehouse.code,
            receiving_location_id=data.item.to_location_id,
            assignee_id=employee.id,
            lot_no=data.actual.lot_no,
            inspection_note=data.actual.remark,
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
        data.item.actual_quantity = data.actual.received_quantity
        return result
