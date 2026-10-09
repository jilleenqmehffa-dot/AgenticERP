from pydantic import ValidationError

from app.contracts.inventory_workflow import InventoryCountReviewDecision
from app.core.enums import TaskType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.schemas.task_workflow import InventoryAdjustmentForm, InventoryCountReviewForm
from app.workflows.inventory_count import InventoryCountWorkflow


class InventoryCountReviewCapability:
    def __init__(self, workflow: InventoryCountWorkflow) -> None:
        self._workflow = workflow

    def validate(self, task: BusinessTask, items: list, actual_data: object) -> InventoryCountReviewForm:
        if task.task_type != TaskType.INVENTORY_COUNT_REVIEW or task.source_type != "INVENTORY_ADJUSTMENT" or task.source_id is None or items:
            raise InvalidTaskDataError("review task must reference one inventory adjustment")
        try:
            return InventoryCountReviewForm.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid inventory review result") from None

    async def execute(
        self, task: BusinessTask, employee: Employee,
        data: InventoryCountReviewForm, trace_id: str,
    ) -> InventoryCountReviewDecision:
        await self._workflow.validate_review_task_in_transaction(task, employee.id)
        reason = data.reason.strip()
        if not reason:
            raise InvalidTaskDataError("inventory review reason is required")
        return InventoryCountReviewDecision(data.decision, reason, employee.id)


class InventoryAdjustmentCapability:
    def __init__(self, workflow: InventoryCountWorkflow) -> None:
        self._workflow = workflow

    def validate(self, task: BusinessTask, items: list, actual_data: object) -> InventoryAdjustmentForm:
        if task.task_type != TaskType.INVENTORY_ADJUSTMENT or task.source_type != "INVENTORY_ADJUSTMENT" or task.source_id is None or items:
            raise InvalidTaskDataError("adjustment task must reference one inventory adjustment")
        try:
            return InventoryAdjustmentForm.model_validate(actual_data)
        except ValidationError:
            raise InvalidTaskDataError("invalid inventory adjustment result") from None

    async def execute(
        self, task: BusinessTask, employee: Employee,
        data: InventoryAdjustmentForm, trace_id: str,
    ) -> None:
        await self._workflow.apply_for_task_in_transaction(
            task, employee_id=employee.id, trace_id=trace_id
        )
