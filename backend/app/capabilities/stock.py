from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from pydantic import ValidationError

from app.contracts.task_execution import StockTaskInput
from app.core.enums import (
    ActorType,
    OutboundStatus,
    ReservationStatus,
    StockStatus,
    WarehouseLocationType,
)
from app.core.exceptions import InvalidTaskDataError, ReservationNotFoundError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee

if TYPE_CHECKING:
    from app.repositories.outbound_order import OutboundOrderRepository
    from app.repositories.stock_reservation import StockReservationRepository
    from app.services.inventory.bucket import InventoryBucketService
    from app.services.inventory.movement import InventoryMovementService
    from app.services.outbound.reservation import ReservationService


@dataclass(frozen=True)
class ValidatedStockTask:
    item: BusinessTaskItem
    actual: StockTaskInput


class _StockCapability:
    def __init__(
        self,
        inventory_movement_service: InventoryMovementService,
    ) -> None:
        self._inventory_movements = inventory_movement_service

    def validate(
        self,
        task: BusinessTask,
        items: list[BusinessTaskItem],
        actual_data: object,
    ) -> ValidatedStockTask:
        try:
            actual = StockTaskInput.model_validate(actual_data)
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
        await self._inventory_movements.stock_in_in_transaction(
            data.item.product_id,
            task.warehouse.code,
            data.actual.actual_quantity,
            reference_type="BUSINESS_TASK",
            reference_id=task.id,
            created_by=str(employee.id),
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
        data.item.actual_quantity = data.actual.actual_quantity


class StockOutCapability(_StockCapability):
    _RESERVED_SHIPMENT_SOURCE_TYPE = "STOCK_RESERVATION"

    def __init__(
        self,
        inventory_movement_service: InventoryMovementService,
        bucket_service: InventoryBucketService,
        reservation_service: ReservationService,
        reservation_repository: StockReservationRepository,
        outbound_repository: OutboundOrderRepository,
    ) -> None:
        super().__init__(inventory_movement_service)
        self._buckets = bucket_service
        self._reservation_service = reservation_service
        self._reservations = reservation_repository
        self._outbound = outbound_repository

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
        if task.source_type == self._RESERVED_SHIPMENT_SOURCE_TYPE:
            await self._ship_reservation(task, employee, data, trace_id)
            return
        if task.source_type == "OUTBOUND_ORDER":
            raise InvalidTaskDataError(
                "reserved stock-out task must reference STOCK_RESERVATION"
            )

        await self._inventory_movements.stock_out_in_transaction(
            data.item.product_id,
            task.warehouse.code,
            data.actual.actual_quantity,
            reference_type="BUSINESS_TASK",
            reference_id=task.id,
            created_by=str(employee.id),
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(employee.id),
            trace_id=trace_id,
        )
        data.item.actual_quantity = data.actual.actual_quantity

    async def _ship_reservation(
        self,
        task: BusinessTask,
        employee: Employee,
        data: ValidatedStockTask,
        trace_id: str,
    ) -> None:
        if task.source_id is None:
            raise InvalidTaskDataError(
                "reserved stock-out task requires a reservation source_id"
            )
        source_bucket = data.item.source_bucket
        from_location = data.item.from_location
        if source_bucket is None or data.item.source_bucket_id is None:
            raise InvalidTaskDataError(
                "reserved stock-out task requires a source bucket"
            )
        if source_bucket.stock_status != StockStatus.PICKING:
            raise InvalidTaskDataError(
                "reserved stock-out task must consume a PICKING bucket"
            )
        if (
            from_location is None
            or not from_location.is_active
            or from_location.location_type != WarehouseLocationType.SHIPPING
            or from_location.warehouse_id != task.warehouse_id
        ):
            raise InvalidTaskDataError(
                "reserved stock-out task must start from an active shipping location"
            )

        reservation = await self._reservations.get_for_update(task.source_id)
        if reservation is None:
            raise ReservationNotFoundError(task.source_id)
        quantity = Decimal(data.actual.actual_quantity)
        if reservation.status != ReservationStatus.ACTIVE:
            raise InvalidTaskDataError("stock reservation is not active")
        if quantity != reservation.quantity or quantity != data.item.planned_quantity:
            raise InvalidTaskDataError(
                "reserved stock-out requires the full reservation quantity"
            )
        if (
            reservation.product_id != data.item.product_id
            or reservation.warehouse_code != task.warehouse.code
            or reservation.location_code != from_location.code
            or source_bucket.product_id != reservation.product_id
            or source_bucket.warehouse_code != reservation.warehouse_code
            or source_bucket.location_code != reservation.location_code
            or source_bucket.lot_no != reservation.lot_no
        ):
            raise InvalidTaskDataError(
                "stock-out task does not match the stock reservation"
            )

        item_reference = await self._outbound.get_item(
            reservation.outbound_order_item_id
        )
        if item_reference is None:
            raise InvalidTaskDataError("outbound order item does not exist")
        order = await self._outbound.get_for_update(
            item_reference.outbound_order_id
        )
        if order is None:
            raise InvalidTaskDataError("outbound order does not exist")
        if (
            order.warehouse_code != reservation.warehouse_code
            or order.status != OutboundStatus.READY_TO_SHIP
        ):
            raise InvalidTaskDataError("outbound order is not ready to ship")
        items = await self._outbound.get_items_for_update(order.id)
        item = next(
            (candidate for candidate in items if candidate.id == item_reference.id),
            None,
        )
        if item is None or item.product_id != reservation.product_id:
            raise InvalidTaskDataError(
                "stock reservation does not match the outbound order item"
            )
        if item.packed_at is None:
            raise InvalidTaskDataError("outbound order item is not packed")
        if item.shipped_quantity + quantity > item.picked_quantity:
            raise InvalidTaskDataError("shipped quantity exceeds picked quantity")

        actor_id = str(employee.id)
        await self._buckets.decrease_in_transaction(
            reservation.product_id,
            reservation.warehouse_code,
            quantity,
            location_code=reservation.location_code,
            lot_no=reservation.lot_no,
            stock_status=StockStatus.PICKING,
            actor_type=ActorType.EMPLOYEE,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        await self._inventory_movements.ship_reserved_in_transaction(
            reservation.product_id,
            reservation.warehouse_code,
            quantity,
            reference_type="STOCK_RESERVATION",
            reference_id=reservation.id,
            created_by=actor_id,
            actor_type=ActorType.EMPLOYEE,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        await self._reservation_service.mark_consumed_in_transaction(
            reservation.id,
            actor_type=ActorType.EMPLOYEE,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        item.shipped_quantity += quantity
        await self._outbound.save_item(item)

        if items and all(
            candidate.shipped_quantity == candidate.requested_quantity
            for candidate in items
        ):
            order.status = OutboundStatus.SHIPPED
            order.shipped_at = datetime.now(timezone.utc)
            await self._outbound.save_order(order)

        data.item.actual_quantity = quantity
