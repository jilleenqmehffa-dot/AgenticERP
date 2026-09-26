import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import (
    InventoryStatus,
    OutboundStatus,
    ReservationStatus,
    StockStatus,
)
from app.core.exceptions import (
    InsufficientStockError,
    InvalidReservationDataError,
    InvalidReservationStateError,
)
from app.models.inventory import Inventory
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.stock_reservation import StockReservation
from app.services.reservation import ReservationService


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session
        self.exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeTransaction":
        self._session.active = True
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        self.exception_type = exception_type
        self._session.active = False
        return False


class FakeSession:
    def __init__(self) -> None:
        self.active = False
        self.transactions: list[FakeTransaction] = []

    def begin(self) -> FakeTransaction:
        transaction = FakeTransaction(self)
        self.transactions.append(transaction)
        return transaction

    def in_transaction(self) -> bool:
        return self.active


class ReservationServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.order = OutboundOrder(
            id=101,
            outbound_no="OUT-101",
            warehouse_code="WH-A",
            status=OutboundStatus.PENDING_OUTBOUND,
        )
        self.item = OutboundOrderItem(
            id=201,
            outbound_order_id=101,
            product_id=1,
            requested_quantity=Decimal("10.000"),
            reserved_quantity=Decimal("2.000"),
            picked_quantity=Decimal("0.000"),
            shipped_quantity=Decimal("0.000"),
        )
        self.inventory = Inventory(
            product_id=1,
            warehouse_code="WH-A",
            on_hand_quantity=Decimal("100.000"),
            reserved_quantity=Decimal("20.000"),
            low_stock_threshold=Decimal("30.000"),
            status=InventoryStatus.NORMAL,
        )
        self.reservations = MagicMock()
        self.reservations.get_by_no_for_update = AsyncMock(return_value=None)
        self.reservations.get_for_update = AsyncMock()

        async def save_reservation(
            reservation: StockReservation,
        ) -> StockReservation:
            reservation.id = reservation.id or 301
            return reservation

        self.reservations.save = AsyncMock(side_effect=save_reservation)
        self.outbound = MagicMock()
        self.outbound.get_item = AsyncMock(return_value=self.item)
        self.outbound.get_for_update = AsyncMock(return_value=self.order)
        self.outbound.get_items_for_update = AsyncMock(return_value=[self.item])
        self.outbound.save_item = AsyncMock(side_effect=lambda item: item)
        self.outbound.save_order = AsyncMock(side_effect=lambda order: order)
        self.inventories = MagicMock()
        self.inventories.get_for_update = AsyncMock(return_value=self.inventory)
        self.inventories.save = AsyncMock(side_effect=lambda inventory: inventory)
        self.buckets = MagicMock()
        self.buckets.move_in_transaction = AsyncMock()
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = ReservationService(
            self.session,  # type: ignore[arg-type]
            self.reservations,
            self.outbound,
            self.inventories,
            self.buckets,
            self.audits,
        )

    async def test_reserve_updates_inventory_bucket_item_and_order(self) -> None:
        result = await self.service.reserve(
            reservation_no="RES-301",
            outbound_order_item_id=201,
            quantity=8,
            location_code="A-01",
            lot_no="LOT-1",
            trace_id="trace-1",
        )

        self.assertEqual(result.id, 301)
        self.assertEqual(result.status, ReservationStatus.ACTIVE)
        self.assertEqual(result.location_code, "A-01")
        self.assertEqual(result.lot_no, "LOT-1")
        self.assertEqual(self.inventory.reserved_quantity, Decimal("28.000"))
        self.assertEqual(self.item.reserved_quantity, Decimal("10.000"))
        self.assertEqual(self.order.status, OutboundStatus.RESERVED)
        self.assertIsNotNone(self.order.reserved_at)
        bucket_call = self.buckets.move_in_transaction.await_args
        self.assertEqual(bucket_call.args, (1, "WH-A", Decimal("8")))
        self.assertEqual(bucket_call.kwargs["from_status"], StockStatus.AVAILABLE)
        self.assertEqual(bucket_call.kwargs["to_status"], StockStatus.RESERVED)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "RESERVE_STOCK")
        self.assertEqual(audit.trace_id, "trace-1")

    async def test_repeated_reservation_number_is_idempotent(self) -> None:
        existing = StockReservation(
            id=301,
            reservation_no="RES-301",
            outbound_order_item_id=201,
            product_id=1,
            warehouse_code="WH-A",
            location_code="A-01",
            lot_no="LOT-1",
            quantity=Decimal("8"),
            status=ReservationStatus.ACTIVE,
        )
        self.reservations.get_by_no_for_update.return_value = existing

        result = await self.service.reserve(
            reservation_no="RES-301",
            outbound_order_item_id=201,
            quantity=8,
            location_code="A-01",
            lot_no="LOT-1",
        )

        self.assertIs(result, existing)
        self.outbound.get_item.assert_not_awaited()
        self.buckets.move_in_transaction.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_reserve_rejects_item_overage_and_insufficient_inventory(self) -> None:
        with self.assertRaises(InvalidReservationDataError):
            await self.service.reserve(
                reservation_no="RES-OVER",
                outbound_order_item_id=201,
                quantity=9,
                location_code="A-01",
            )

        self.item.reserved_quantity = Decimal("0")
        self.inventory.reserved_quantity = Decimal("95")
        with self.assertRaises(InsufficientStockError):
            await self.service.reserve(
                reservation_no="RES-STOCK",
                outbound_order_item_id=201,
                quantity=10,
                location_code="A-01",
            )

        self.buckets.move_in_transaction.assert_not_awaited()
        self.reservations.save.assert_not_awaited()

    async def test_release_restores_available_bucket_and_quantities(self) -> None:
        reservation = StockReservation(
            id=301,
            reservation_no="RES-301",
            outbound_order_item_id=201,
            product_id=1,
            warehouse_code="WH-A",
            location_code="A-01",
            lot_no="LOT-1",
            quantity=Decimal("8.000"),
            status=ReservationStatus.ACTIVE,
        )
        self.reservations.get_for_update.return_value = reservation
        self.item.reserved_quantity = Decimal("10.000")
        self.inventory.reserved_quantity = Decimal("28.000")
        self.order.status = OutboundStatus.RESERVED

        result = await self.service.release(301, trace_id="trace-release")

        self.assertIs(result, reservation)
        self.assertEqual(reservation.status, ReservationStatus.RELEASED)
        self.assertIsNotNone(reservation.released_at)
        self.assertEqual(self.inventory.reserved_quantity, Decimal("20.000"))
        self.assertEqual(self.item.reserved_quantity, Decimal("2.000"))
        self.assertEqual(self.order.status, OutboundStatus.PENDING_OUTBOUND)
        bucket_call = self.buckets.move_in_transaction.await_args
        self.assertEqual(bucket_call.kwargs["from_status"], StockStatus.RESERVED)
        self.assertEqual(bucket_call.kwargs["to_status"], StockStatus.AVAILABLE)
        self.assertEqual(
            self.audits.append.await_args.args[0].action,
            "RELEASED_STOCK_RESERVATION",
        )

    async def test_expire_requires_elapsed_expiration(self) -> None:
        reservation = StockReservation(
            id=302,
            reservation_no="RES-302",
            outbound_order_item_id=201,
            product_id=1,
            warehouse_code="WH-A",
            location_code="A-01",
            lot_no="",
            quantity=Decimal("1"),
            status=ReservationStatus.ACTIVE,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        self.reservations.get_for_update.return_value = reservation

        with self.assertRaises(InvalidReservationStateError):
            await self.service.expire(302)

        self.buckets.move_in_transaction.assert_not_awaited()
        self.reservations.save.assert_not_awaited()

    async def test_mark_consumed_requires_outer_transaction_and_is_idempotent(
        self,
    ) -> None:
        reservation = StockReservation(
            id=303,
            reservation_no="RES-303",
            outbound_order_item_id=201,
            product_id=1,
            warehouse_code="WH-A",
            location_code="A-01",
            lot_no="LOT-1",
            quantity=Decimal("2"),
            status=ReservationStatus.ACTIVE,
        )
        self.reservations.get_for_update.return_value = reservation

        with self.assertRaisesRegex(RuntimeError, "active transaction"):
            await self.service.mark_consumed_in_transaction(303)

        self.session.active = True
        result = await self.service.mark_consumed_in_transaction(303)
        repeated = await self.service.mark_consumed_in_transaction(303)

        self.assertIs(result, reservation)
        self.assertIs(repeated, reservation)
        self.assertEqual(reservation.status, ReservationStatus.CONSUMED)
        self.assertIsNotNone(reservation.consumed_at)
        self.assertEqual(self.reservations.save.await_count, 1)
        self.audits.append.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
