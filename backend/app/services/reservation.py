from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    OutboundStatus,
    ReservationStatus,
    StockStatus,
)
from app.core.exceptions import (
    InsufficientReservedStockError,
    InvalidReservationDataError,
    InvalidReservationStateError,
    OutboundOrderItemNotFoundError,
    ReservationNotFoundError,
)
from app.models.audit_log import AuditLog
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.stock_reservation import StockReservation
from app.repositories.audit_log import AuditLogRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.outbound_order import OutboundOrderRepository
from app.repositories.stock_reservation import StockReservationRepository
from app.services.inventory_balance import InventoryBalanceService
from app.services.inventory_bucket import InventoryBucketService


class ReservationService:
    def __init__(
        self,
        session: AsyncSession,
        reservation_repository: StockReservationRepository | None = None,
        outbound_repository: OutboundOrderRepository | None = None,
        inventory_repository: InventoryRepository | None = None,
        bucket_service: InventoryBucketService | None = None,
        audit_repository: AuditLogRepository | None = None,
        balance_service: InventoryBalanceService | None = None,
    ) -> None:
        self._session = session
        self._reservations = reservation_repository or StockReservationRepository(
            session
        )
        self._outbound = outbound_repository or OutboundOrderRepository(session)
        self._balances = balance_service or InventoryBalanceService(
            session,
            inventory_repository,
        )
        self._buckets = bucket_service or InventoryBucketService(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def reserve(
        self,
        *,
        reservation_no: str,
        outbound_order_item_id: int,
        quantity: Decimal | int,
        location_code: str = "",
        lot_no: str = "",
        expires_at: datetime | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> StockReservation:
        values = self._validate_reserve(
            reservation_no=reservation_no,
            outbound_order_item_id=outbound_order_item_id,
            quantity=quantity,
            location_code=location_code,
            lot_no=lot_no,
            expires_at=expires_at,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        async with self._session.begin():
            existing = await self._reservations.get_by_no_for_update(
                values["reservation_no"]
            )
            if existing is not None:
                self._validate_idempotent_reservation(existing, values)
                return existing

            item_reference = await self._outbound.get_item(
                values["outbound_order_item_id"]
            )
            if item_reference is None:
                raise OutboundOrderItemNotFoundError(
                    values["outbound_order_item_id"]
                )
            order = await self._outbound.get_for_update(
                item_reference.outbound_order_id
            )
            if order is None:
                raise InvalidReservationDataError("outbound order does not exist")
            if order.status != OutboundStatus.PENDING_OUTBOUND:
                raise InvalidReservationDataError(
                    "outbound order state does not allow reservation"
                )
            existing = await self._reservations.get_by_no_for_update(
                values["reservation_no"]
            )
            if existing is not None:
                self._validate_idempotent_reservation(existing, values)
                return existing

            items = await self._outbound.get_items_for_update(order.id)
            item = self._find_item(
                items,
                values["outbound_order_item_id"],
            )

            remaining = item.requested_quantity - item.reserved_quantity
            if remaining < values["quantity"]:
                raise InvalidReservationDataError(
                    "reservation quantity exceeds outbound item remainder"
                )
            balance_change = await self._balances.reserve_in_transaction(
                item.product_id,
                order.warehouse_code,
                values["quantity"],
            )
            inventory = balance_change.inventory

            await self._buckets.move_in_transaction(
                item.product_id,
                order.warehouse_code,
                values["quantity"],
                from_location_code=values["location_code"],
                from_lot_no=values["lot_no"],
                from_status=StockStatus.AVAILABLE,
                to_location_code=values["location_code"],
                to_lot_no=values["lot_no"],
                to_status=StockStatus.RESERVED,
                actor_type=values["actor_type"],
                actor_id=values["actor_id"],
                trace_id=values["trace_id"],
            )

            inventory_before = Decimal(
                balance_change.before_data["reserved_quantity"]
            )

            item_before = item.reserved_quantity
            item.reserved_quantity += values["quantity"]
            await self._outbound.save_item(item)

            reservation = StockReservation(
                reservation_no=values["reservation_no"],
                outbound_order_item_id=item.id,
                product_id=item.product_id,
                warehouse_code=order.warehouse_code,
                location_code=values["location_code"],
                lot_no=values["lot_no"],
                quantity=values["quantity"],
                status=ReservationStatus.ACTIVE,
                expires_at=values["expires_at"],
            )
            await self._reservations.save(reservation)

            if items and all(
                outbound_item.reserved_quantity
                == outbound_item.requested_quantity
                for outbound_item in items
            ):
                order.status = OutboundStatus.RESERVED
                order.reserved_at = datetime.now(timezone.utc)
                await self._outbound.save_order(order)

            await self._audits.append(
                self._reservation_audit(
                    reservation,
                    action="RESERVE_STOCK",
                    actor_type=values["actor_type"],
                    actor_id=values["actor_id"],
                    trace_id=values["trace_id"],
                    before_status=None,
                    inventory_before=inventory_before,
                    inventory_after=inventory.reserved_quantity,
                    item_before=item_before,
                    item_after=item.reserved_quantity,
                )
            )
            return reservation

    async def release(
        self,
        reservation_id: int,
        *,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> StockReservation:
        return await self._release_with_status(
            reservation_id,
            ReservationStatus.RELEASED,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )

    async def expire(
        self,
        reservation_id: int,
        *,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> StockReservation:
        return await self._release_with_status(
            reservation_id,
            ReservationStatus.EXPIRED,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
            require_expired=True,
        )

    async def cancel(
        self,
        reservation_id: int,
        *,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> StockReservation:
        return await self._release_with_status(
            reservation_id,
            ReservationStatus.CANCELLED,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )

    async def mark_consumed_in_transaction(
        self,
        reservation_id: int,
        *,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> StockReservation:
        """Mark consumed only after physical shipment succeeds in this transaction."""
        if not self._session.in_transaction():
            raise RuntimeError(
                "mark_consumed_in_transaction requires an active transaction"
            )
        reservation_id = self._positive_id(reservation_id, "reservation_id")
        actor_type = self._actor_type(actor_type)
        actor_id = self._actor_id(actor_type, actor_id)
        trace_id = self._trace_id(trace_id)
        reservation = await self._reservations.get_for_update(reservation_id)
        if reservation is None:
            raise ReservationNotFoundError(reservation_id)
        if reservation.status == ReservationStatus.CONSUMED:
            return reservation
        if reservation.status != ReservationStatus.ACTIVE:
            raise InvalidReservationStateError(reservation_id)
        before_status = reservation.status
        reservation.status = ReservationStatus.CONSUMED
        reservation.consumed_at = datetime.now(timezone.utc)
        await self._reservations.save(reservation)
        await self._audits.append(
            self._reservation_audit(
                reservation,
                action="CONSUME_STOCK_RESERVATION",
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                before_status=before_status,
            )
        )
        return reservation

    async def _release_with_status(
        self,
        reservation_id: int,
        target_status: ReservationStatus,
        *,
        actor_type: ActorType,
        actor_id: str | None,
        trace_id: str | None,
        require_expired: bool = False,
    ) -> StockReservation:
        reservation_id = self._positive_id(reservation_id, "reservation_id")
        actor_type = self._actor_type(actor_type)
        audit_actor_id = self._actor_id(actor_type, actor_id)
        trace_id = self._trace_id(trace_id)
        async with self._session.begin():
            reservation = await self._reservations.get_for_update(reservation_id)
            if reservation is None:
                raise ReservationNotFoundError(reservation_id)
            if reservation.status == target_status:
                return reservation
            if reservation.status != ReservationStatus.ACTIVE:
                raise InvalidReservationStateError(reservation_id)
            now = datetime.now(timezone.utc)
            if require_expired and (
                reservation.expires_at is None or reservation.expires_at > now
            ):
                raise InvalidReservationStateError(reservation_id)

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
                raise InvalidReservationDataError("outbound order does not exist")
            if order.status not in {
                OutboundStatus.PENDING_OUTBOUND,
                OutboundStatus.RESERVED,
            }:
                raise InvalidReservationStateError(reservation_id)
            items = await self._outbound.get_items_for_update(order.id)
            item = self._find_item(
                items,
                reservation.outbound_order_item_id,
            )
            if item.reserved_quantity < reservation.quantity:
                raise InvalidReservationDataError(
                    "outbound item reserved quantity is inconsistent"
                )

            try:
                balance_change = (
                    await self._balances.release_reserved_in_transaction(
                        reservation.product_id,
                        reservation.warehouse_code,
                        reservation.quantity,
                    )
                )
            except InsufficientReservedStockError:
                raise InvalidReservationDataError(
                    "inventory reserved quantity is inconsistent"
                ) from None
            inventory = balance_change.inventory

            await self._buckets.move_in_transaction(
                reservation.product_id,
                reservation.warehouse_code,
                reservation.quantity,
                from_location_code=reservation.location_code,
                from_lot_no=reservation.lot_no,
                from_status=StockStatus.RESERVED,
                to_location_code=reservation.location_code,
                to_lot_no=reservation.lot_no,
                to_status=StockStatus.AVAILABLE,
                actor_type=actor_type,
                actor_id=audit_actor_id,
                trace_id=trace_id,
            )

            inventory_before = Decimal(
                balance_change.before_data["reserved_quantity"]
            )

            item_before = item.reserved_quantity
            item.reserved_quantity -= reservation.quantity
            await self._outbound.save_item(item)

            before_status = reservation.status
            reservation.status = target_status
            reservation.released_at = now
            await self._reservations.save(reservation)

            if order.status == OutboundStatus.RESERVED:
                order.status = OutboundStatus.PENDING_OUTBOUND
                order.reserved_at = None
                await self._outbound.save_order(order)

            await self._audits.append(
                self._reservation_audit(
                    reservation,
                    action=f"{target_status.value}_STOCK_RESERVATION",
                    actor_type=actor_type,
                    actor_id=audit_actor_id,
                    trace_id=trace_id,
                    before_status=before_status,
                    inventory_before=inventory_before,
                    inventory_after=inventory.reserved_quantity,
                    item_before=item_before,
                    item_after=item.reserved_quantity,
                )
            )
            return reservation

    @staticmethod
    def _find_item(
        items: list[OutboundOrderItem],
        item_id: int,
    ) -> OutboundOrderItem:
        for item in items:
            if item.id == item_id:
                return item
        raise OutboundOrderItemNotFoundError(item_id)

    @classmethod
    def _validate_reserve(cls, **values: object) -> dict[str, object]:
        reservation_no = cls._required_code(
            values["reservation_no"],
            "reservation_no",
            64,
        )
        outbound_item_id = cls._positive_id(
            values["outbound_order_item_id"],
            "outbound_order_item_id",
        )
        quantity = cls._quantity(values["quantity"])
        location_code = cls._optional_code(
            values["location_code"],
            "location_code",
            64,
        )
        lot_no = cls._optional_code(values["lot_no"], "lot_no", 100)
        expires_at = values["expires_at"]
        if expires_at is not None:
            if not isinstance(expires_at, datetime) or expires_at.tzinfo is None:
                raise InvalidReservationDataError(
                    "expires_at must be a timezone-aware datetime"
                )
        actor_type = cls._actor_type(values["actor_type"])
        return {
            "reservation_no": reservation_no,
            "outbound_order_item_id": outbound_item_id,
            "quantity": quantity,
            "location_code": location_code,
            "lot_no": lot_no,
            "expires_at": expires_at,
            "actor_type": actor_type,
            "actor_id": cls._actor_id(actor_type, values["actor_id"]),
            "trace_id": cls._trace_id(values["trace_id"]),
        }

    @staticmethod
    def _validate_idempotent_reservation(
        reservation: StockReservation,
        values: dict[str, object],
    ) -> None:
        if (
            reservation.outbound_order_item_id
            != values["outbound_order_item_id"]
            or reservation.quantity != values["quantity"]
            or reservation.location_code != values["location_code"]
            or reservation.lot_no != values["lot_no"]
            or reservation.expires_at != values["expires_at"]
        ):
            raise InvalidReservationDataError(
                "reservation_no already exists with different data"
            )

    @staticmethod
    def _positive_id(value: object, field_name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise InvalidReservationDataError(
                f"{field_name} must be a positive integer"
            )
        return value

    @staticmethod
    def _quantity(value: object) -> Decimal:
        try:
            quantity = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            raise InvalidReservationDataError("quantity must be numeric") from None
        if not quantity.is_finite() or quantity <= 0:
            raise InvalidReservationDataError(
                "quantity must be greater than zero"
            )
        return quantity

    @staticmethod
    def _required_code(value: object, field_name: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidReservationDataError(
                f"{field_name} must be a nonempty string"
            )
        normalized = value.strip()
        if len(normalized) > max_length:
            raise InvalidReservationDataError(
                f"{field_name} exceeds {max_length} characters"
            )
        return normalized

    @staticmethod
    def _optional_code(value: object, field_name: str, max_length: int) -> str:
        if not isinstance(value, str):
            raise InvalidReservationDataError(f"{field_name} must be a string")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise InvalidReservationDataError(
                f"{field_name} exceeds {max_length} characters"
            )
        return normalized

    @staticmethod
    def _actor_type(value: object) -> ActorType:
        if not isinstance(value, ActorType):
            raise InvalidReservationDataError("actor_type is invalid")
        return value

    @staticmethod
    def _actor_id(actor_type: ActorType, value: object) -> str:
        if value is None and actor_type == ActorType.SYSTEM:
            return "SYSTEM"
        if not isinstance(value, str) or not value.strip():
            raise InvalidReservationDataError(
                "actor_id is required for this actor_type"
            )
        normalized = value.strip()
        if len(normalized) > 255:
            raise InvalidReservationDataError("actor_id exceeds 255 characters")
        return normalized

    @staticmethod
    def _trace_id(value: object) -> str:
        if value is None:
            return str(uuid4())
        if not isinstance(value, str) or not value.strip():
            raise InvalidReservationDataError(
                "trace_id must be a nonempty string"
            )
        normalized = value.strip()
        if len(normalized) > 64:
            raise InvalidReservationDataError("trace_id exceeds 64 characters")
        return normalized

    @staticmethod
    def _reservation_audit(
        reservation: StockReservation,
        *,
        action: str,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
        before_status: ReservationStatus | None,
        inventory_before: Decimal | None = None,
        inventory_after: Decimal | None = None,
        item_before: Decimal | None = None,
        item_after: Decimal | None = None,
    ) -> AuditLog:
        return AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            entity_type="STOCK_RESERVATION",
            entity_id=str(reservation.id),
            before_data={
                "status": before_status.value if before_status else None,
                "inventory_reserved_quantity": (
                    str(inventory_before) if inventory_before is not None else None
                ),
                "item_reserved_quantity": (
                    str(item_before) if item_before is not None else None
                ),
            },
            after_data={
                "status": reservation.status.value,
                "inventory_reserved_quantity": (
                    str(inventory_after) if inventory_after is not None else None
                ),
                "item_reserved_quantity": (
                    str(item_after) if item_after is not None else None
                ),
            },
            trace_id=trace_id,
            metadata_={
                "outbound_order_item_id": reservation.outbound_order_item_id,
                "product_id": reservation.product_id,
                "warehouse_code": reservation.warehouse_code,
                "location_code": reservation.location_code,
                "lot_no": reservation.lot_no,
                "quantity": str(reservation.quantity),
            },
        )
