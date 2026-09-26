from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.capabilities.packing import PackingCapability
from app.capabilities.receiving import ReceiveCapability
from app.capabilities.stock import StockInCapability, StockOutCapability
from app.core.enums import TaskType
from app.core.exceptions import UnsupportedTaskTypeError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.services.inventory import InventoryService
    from app.services.packing import PackingService
    from app.services.receiving import ReceivingService


class CapabilityDispatcher:
    _SUPPORTED_TYPES = {
        TaskType.RECEIVE,
        TaskType.STOCK_IN,
        TaskType.STOCK_OUT,
        TaskType.PACK,
    }

    def __init__(
        self,
        inventory_service: InventoryService,
        packing_service: PackingService,
        receiving_service: ReceivingService,
    ) -> None:
        self._capabilities = {
            TaskType.STOCK_IN: StockInCapability(inventory_service),
            TaskType.STOCK_OUT: StockOutCapability(inventory_service),
            TaskType.PACK: PackingCapability(packing_service),
            TaskType.RECEIVE: ReceiveCapability(receiving_service),
        }

    @classmethod
    def supports(cls, task_type: TaskType) -> bool:
        return task_type in cls._SUPPORTED_TYPES

    async def execute(
        self,
        task: BusinessTask,
        employee: Employee,
        items: list[BusinessTaskItem],
        actual_data: dict[str, Any],
        trace_id: str,
    ) -> None:
        capability = self._capabilities.get(task.task_type)
        if capability is None:
            raise UnsupportedTaskTypeError(task.task_type)
        validated = capability.validate(task, items, actual_data)
        await capability.execute(task, employee, validated, trace_id)
