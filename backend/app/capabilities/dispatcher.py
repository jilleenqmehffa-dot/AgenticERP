from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.capabilities.packing import PackingCapability
from app.capabilities.picking import PickCapability
from app.capabilities.putaway import PutawayCapability
from app.capabilities.receiving import ReceiveCapability
from app.capabilities.stock import StockInCapability, StockOutCapability
from app.core.enums import TaskType
from app.core.exceptions import UnsupportedTaskTypeError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.repositories.outbound_order import OutboundOrderRepository
    from app.repositories.stock_reservation import StockReservationRepository
    from app.services.inventory_bucket import InventoryBucketService
    from app.services.inventory_movement import InventoryMovementService
    from app.services.packing import PackingService
    from app.services.picking import PickingService
    from app.services.receiving import ReceivingService
    from app.services.reservation import ReservationService


class CapabilityDispatcher:
    _SUPPORTED_TYPES = {
        TaskType.RECEIVE,
        TaskType.STOCK_IN,
        TaskType.STOCK_OUT,
        TaskType.PACK,
        TaskType.PUTAWAY,
        TaskType.PICK,
    }

    def __init__(
        self,
        inventory_movement_service: InventoryMovementService,
        packing_service: PackingService,
        receiving_service: ReceivingService,
        bucket_service: InventoryBucketService,
        picking_service: PickingService,
        reservation_service: ReservationService,
        reservation_repository: StockReservationRepository,
        outbound_repository: OutboundOrderRepository,
    ) -> None:
        self._capabilities = {
            TaskType.STOCK_IN: StockInCapability(inventory_movement_service),
            TaskType.STOCK_OUT: StockOutCapability(
                inventory_movement_service,
                bucket_service,
                reservation_service,
                reservation_repository,
                outbound_repository,
            ),
            TaskType.PACK: PackingCapability(packing_service),
            TaskType.RECEIVE: ReceiveCapability(receiving_service),
            TaskType.PUTAWAY: PutawayCapability(
                bucket_service,
                inventory_movement_service,
            ),
            TaskType.PICK: PickCapability(picking_service),
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
