from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, OutboundStatus, ReservationStatus, StockStatus
from app.core.exceptions import (
    InvalidPickingDataError,
    InvalidPickingStateError,
    OutboundOrderItemNotFoundError,
    ReservationNotFoundError,
)
from app.core.validation import (
    actor_id as validate_actor_id,
    actor_type as validate_actor_type,
    positive_int,
    trace_id as validate_trace_id,
)
from app.models.audit_log import AuditLog
from app.models.outbound_order_item import OutboundOrderItem
from app.models.stock_reservation import StockReservation
from app.repositories.audit_log import AuditLogRepository
from app.repositories.outbound_order import OutboundOrderRepository
from app.repositories.stock_reservation import StockReservationRepository
from app.services.inventory.bucket import InventoryBucketService


class PickingService:
    def __init__(
        self,
        session: AsyncSession,
        reservation_repository: StockReservationRepository | None = None,
        outbound_repository: OutboundOrderRepository | None = None,
        bucket_service: InventoryBucketService | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._reservations = reservation_repository or StockReservationRepository(
            session
        )
        self._outbound = outbound_repository or OutboundOrderRepository(session)
        self._buckets = bucket_service or InventoryBucketService(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def pick(
        self,
        reservation_id: int,
        *,
        quantity: Decimal | int,
        to_location_code: str,
        expected_product_id: int,
        expected_from_location_code: str,
        expected_lot_no: str,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> StockReservation:
        values = self._validate(
            reservation_id=reservation_id,
            quantity=quantity,
            to_location_code=to_location_code,
            expected_product_id=expected_product_id,
            expected_from_location_code=expected_from_location_code,
            expected_lot_no=expected_lot_no,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        async with self._session.begin():
            return await self._pick_in_transaction(**values)

    async def pick_in_transaction(
        self,
        reservation_id: int,
        *,
        quantity: Decimal | int,
        to_location_code: str,
        expected_product_id: int,
        expected_from_location_code: str,
        expected_lot_no: str,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> StockReservation:
        if not self._session.in_transaction():
            raise RuntimeError("pick_in_transaction requires an active transaction")
        values = self._validate(
            reservation_id=reservation_id,
            quantity=quantity,
            to_location_code=to_location_code,
            expected_product_id=expected_product_id,
            expected_from_location_code=expected_from_location_code,
            expected_lot_no=expected_lot_no,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        return await self._pick_in_transaction(**values)

    async def _pick_in_transaction(
        self,
        *,
        reservation_id: int,
        quantity: Decimal,
        to_location_code: str,
        expected_product_id: int,
        expected_from_location_code: str,
        expected_lot_no: str,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> StockReservation:
        reservation = await self._reservations.get_for_update(reservation_id)
        if reservation is None:
            raise ReservationNotFoundError(reservation_id)
        if reservation.status != ReservationStatus.ACTIVE:
            raise InvalidPickingStateError(reservation_id)
        if quantity != reservation.quantity:
            raise InvalidPickingDataError(
                "initial picking flow requires the full reservation quantity"
            )
        if (
            reservation.product_id != expected_product_id
            or reservation.location_code != expected_from_location_code
            or reservation.lot_no != expected_lot_no
        ):
            raise InvalidPickingDataError(
                "picking task does not match the stock reservation"
            )
        if reservation.location_code == to_location_code:
            raise InvalidPickingDataError(
                "picking source and destination locations must differ"
            )

        item_reference = await self._outbound.get_item(
            reservation.outbound_order_item_id
        )
        if item_reference is None:
            raise OutboundOrderItemNotFoundError(
                reservation.outbound_order_item_id
            )
        order = await self._outbound.get_for_update(
            item_reference.outbound_order_id
        )
        if order is None:
            raise InvalidPickingDataError("outbound order does not exist")
        if (
            order.warehouse_code != reservation.warehouse_code
            or item_reference.product_id != reservation.product_id
        ):
            raise InvalidPickingDataError(
                "stock reservation does not match the outbound order item"
            )
        if order.status not in {OutboundStatus.RESERVED, OutboundStatus.PICKING}:
            raise InvalidPickingStateError(reservation_id)
        item = await self._outbound.get_item_for_update(item_reference.id)
        if item is None:
            raise OutboundOrderItemNotFoundError(item_reference.id)
        if item.picked_quantity + quantity > item.reserved_quantity:
            raise InvalidPickingDataError(
                "picked quantity exceeds reserved quantity"
            )

        before_location = reservation.location_code
        before_picked = item.picked_quantity
        await self._buckets.move_in_transaction(
            reservation.product_id,
            reservation.warehouse_code,
            quantity,
            from_location_code=reservation.location_code,
            from_lot_no=reservation.lot_no,
            from_status=StockStatus.RESERVED,
            to_location_code=to_location_code,
            to_lot_no=reservation.lot_no,
            to_status=StockStatus.PICKING,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        reservation.location_code = to_location_code
        await self._reservations.save(reservation)
        item.picked_quantity += quantity
        await self._outbound.save_item(item)

        if order.status == OutboundStatus.RESERVED:
            order.status = OutboundStatus.PICKING
            order.picking_started_at = datetime.now(timezone.utc)
            await self._outbound.save_order(order)

        await self._audits.append(
            self._audit(
                reservation,
                item,
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                before_location=before_location,
                before_picked=before_picked,
            )
        )
        return reservation

    @staticmethod
    def _audit(
        reservation: StockReservation,
        item: OutboundOrderItem,
        *,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
        before_location: str,
        before_picked: Decimal,
    ) -> AuditLog:
        return AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action="PICK_RESERVED_STOCK",
            entity_type="STOCK_RESERVATION",
            entity_id=str(reservation.id),
            before_data={
                "location_code": before_location,
                "stock_status": StockStatus.RESERVED.value,
                "item_picked_quantity": str(before_picked),
            },
            after_data={
                "location_code": reservation.location_code,
                "stock_status": StockStatus.PICKING.value,
                "item_picked_quantity": str(item.picked_quantity),
            },
            trace_id=trace_id,
            metadata_={
                "outbound_order_item_id": item.id,
                "quantity": str(reservation.quantity),
                "lot_no": reservation.lot_no,
            },
        )

    @classmethod
    def _validate(cls, **values: object) -> dict[str, object]:
        actor_type = cls._actor_type(values["actor_type"])
        return {
            "reservation_id": cls._positive_id(
                values["reservation_id"], "reservation_id"
            ),
            "quantity": cls._quantity(values["quantity"]),
            "to_location_code": cls._required_code(
                values["to_location_code"], "to_location_code", 64
            ),
            "expected_product_id": cls._positive_id(
                values["expected_product_id"], "expected_product_id"
            ),
            "expected_from_location_code": cls._required_code(
                values["expected_from_location_code"],
                "expected_from_location_code",
                64,
            ),
            "expected_lot_no": cls._optional_code(
                values["expected_lot_no"], "expected_lot_no", 100
            ),
            "actor_type": actor_type,
            "actor_id": cls._actor_id(actor_type, values["actor_id"]),
            "trace_id": cls._trace_id(values["trace_id"]),
        }

    @staticmethod
    def _positive_id(value: object, field_name: str) -> int:
        return positive_int(value, field_name, error=InvalidPickingDataError)

    @staticmethod
    def _quantity(value: object) -> Decimal:
        try:
            quantity = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise InvalidPickingDataError("quantity must be numeric") from None
        if not quantity.is_finite() or quantity <= 0:
            raise InvalidPickingDataError("quantity must be greater than zero")
        return quantity

    @staticmethod
    def _required_code(value: object, field_name: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidPickingDataError(f"{field_name} must be a nonempty string")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise InvalidPickingDataError(f"{field_name} is too long")
        return normalized

    @staticmethod
    def _optional_code(value: object, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise InvalidPickingDataError(f"{field_name} must be a string")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise InvalidPickingDataError(f"{field_name} is too long")
        return normalized

    @staticmethod
    def _actor_type(value: object) -> ActorType:
        return validate_actor_type(value, error=InvalidPickingDataError)

    @staticmethod
    def _actor_id(actor_type: ActorType, value: object) -> str:
        return validate_actor_id(
            actor_type,
            value,
            error=InvalidPickingDataError,
        )

    @staticmethod
    def _trace_id(value: object) -> str:
        return validate_trace_id(value, error=InvalidPickingDataError)
