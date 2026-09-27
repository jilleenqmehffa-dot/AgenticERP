import json
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import ActorType, InventoryStatus, MovementType
from app.core.exceptions import (
    InsufficientReservedStockError,
    InsufficientStockError,
    InvalidInventoryDataError,
    InvalidStockQuantityError,
    InventoryNotFoundError,
)
from app.models.inventory import Inventory
from app.services.inventory_movement import InventoryMovementService


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
        self.transaction = FakeTransaction(self)
        self.begin_calls = 0

    def begin(self) -> FakeTransaction:
        self.begin_calls += 1
        self.transaction = FakeTransaction(self)
        return self.transaction

    def in_transaction(self) -> bool:
        return self.active


def make_inventory(
    *,
    on_hand: str = "100.000",
    reserved: str = "0.000",
    threshold: str = "30.000",
) -> Inventory:
    return Inventory(
        product_id=1,
        warehouse_code="WH-A",
        on_hand_quantity=Decimal(on_hand),
        reserved_quantity=Decimal(reserved),
        low_stock_threshold=Decimal(threshold),
        status=InventoryStatus.NORMAL,
    )


class InventoryMovementServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.inventories = MagicMock()
        self.inventories.get_for_update = AsyncMock()
        self.inventories.save = AsyncMock(side_effect=lambda inventory: inventory)
        self.movements = MagicMock()
        self.movements.save = AsyncMock(side_effect=lambda movement: movement)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = InventoryMovementService(
            self.session,  # type: ignore[arg-type]
            self.inventories,
            self.movements,
            self.audits,
        )

    async def test_stock_out_updates_inventory_status_and_creates_movement(self) -> None:
        inventory = make_inventory(threshold="70.000")
        self.inventories.get_for_update.return_value = inventory

        result = await self.service.stock_out(
            1,
            "WH-A",
            40,
            reference_type="SALES_ORDER",
            reference_id=1001,
            created_by="operator-1",
            actor_type=ActorType.EMPLOYEE,
            actor_id="operator-1",
        )

        self.assertIs(result, inventory)
        self.assertEqual(inventory.on_hand_quantity, Decimal("60.000"))
        self.assertEqual(inventory.status, InventoryStatus.LOW_STOCK)
        self.inventories.get_for_update.assert_awaited_once_with(1, "WH-A")
        self.inventories.save.assert_awaited_once_with(inventory)
        movement = self.movements.save.await_args.args[0]
        self.assertEqual(movement.movement_type, MovementType.OUT)
        self.assertEqual(movement.quantity, Decimal("40"))
        self.assertEqual(movement.reference_type, "SALES_ORDER")
        self.assertEqual(movement.reference_id, 1001)
        self.assertEqual(movement.created_by, "operator-1")
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "STOCK_OUT")
        self.assertEqual(audit.entity_type, "INVENTORY")
        self.assertEqual(audit.entity_id, "1:WH-A")
        self.assertEqual(audit.actor_type, ActorType.EMPLOYEE)
        self.assertEqual(audit.actor_id, "operator-1")
        self.assertEqual(audit.before_data["on_hand_quantity"], "100.000")
        self.assertEqual(audit.after_data["on_hand_quantity"], "60.000")
        self.assertEqual(audit.metadata_["quantity"], "40")
        self.assertEqual(audit.metadata_["movement_created_by"], "operator-1")
        json.dumps(audit.before_data)
        json.dumps(audit.after_data)
        json.dumps(audit.metadata_)
        self.assertEqual(self.session.begin_calls, 1)

    async def test_stock_in_updates_inventory_status_and_creates_movement(self) -> None:
        inventory = make_inventory(on_hand="60.000", threshold="70.000")
        inventory.status = InventoryStatus.LOW_STOCK
        self.inventories.get_for_update.return_value = inventory

        result = await self.service.stock_in(1, "WH-A", Decimal("20.000"))

        self.assertIs(result, inventory)
        self.assertEqual(inventory.on_hand_quantity, Decimal("80.000"))
        self.assertEqual(inventory.status, InventoryStatus.NORMAL)
        movement = self.movements.save.await_args.args[0]
        self.assertEqual(movement.movement_type, MovementType.IN)
        self.assertEqual(movement.quantity, Decimal("20.000"))
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "STOCK_IN")
        self.assertEqual(audit.actor_type, ActorType.SYSTEM)
        self.assertEqual(audit.actor_id, "SYSTEM")
        self.assertEqual(audit.before_data["status"], InventoryStatus.LOW_STOCK)
        self.assertEqual(audit.after_data["status"], InventoryStatus.NORMAL)

    async def test_stock_out_uses_available_not_on_hand_quantity(self) -> None:
        inventory = make_inventory(on_hand="100.000", reserved="80.000")
        self.inventories.get_for_update.return_value = inventory

        with self.assertRaises(InsufficientStockError) as raised:
            await self.service.stock_out(1, "WH-A", 30)

        self.assertEqual(raised.exception.available_quantity, Decimal("20.000"))
        self.assertEqual(inventory.on_hand_quantity, Decimal("100.000"))
        self.inventories.save.assert_not_awaited()
        self.movements.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_stock_out_does_not_consume_reserved_quantity(self) -> None:
        inventory = make_inventory(on_hand="100.000", reserved="30.000")
        self.inventories.get_for_update.return_value = inventory

        await self.service.stock_out(1, "WH-A", 20)

        self.assertEqual(inventory.on_hand_quantity, Decimal("80.000"))
        self.assertEqual(inventory.reserved_quantity, Decimal("30.000"))
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "STOCK_OUT")
        self.assertEqual(audit.before_data["reserved_quantity"], "30.000")
        self.assertEqual(audit.after_data["reserved_quantity"], "30.000")

    async def test_ship_reserved_consumes_on_hand_and_reserved_together(self) -> None:
        inventory = make_inventory(
            on_hand="100.000",
            reserved="60.000",
            threshold="50.000",
        )
        self.inventories.get_for_update.return_value = inventory

        result = await self.service.ship_reserved(
            1,
            "WH-A",
            40,
            reference_type="OUTBOUND_ORDER",
            reference_id=2001,
        )

        self.assertIs(result, inventory)
        self.assertEqual(inventory.on_hand_quantity, Decimal("60.000"))
        self.assertEqual(inventory.reserved_quantity, Decimal("20.000"))
        self.assertEqual(inventory.available_quantity, Decimal("40.000"))
        self.assertEqual(inventory.status, InventoryStatus.LOW_STOCK)
        movement = self.movements.save.await_args.args[0]
        self.assertEqual(movement.movement_type, MovementType.OUT)
        self.assertEqual(movement.quantity, Decimal("40"))
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "SHIP_RESERVED")
        self.assertEqual(audit.before_data["reserved_quantity"], "60.000")
        self.assertEqual(audit.after_data["reserved_quantity"], "20.000")

    async def test_ship_reserved_rejects_quantity_above_reservation(self) -> None:
        inventory = make_inventory(on_hand="100.000", reserved="20.000")
        self.inventories.get_for_update.return_value = inventory

        with self.assertRaises(InsufficientReservedStockError) as raised:
            await self.service.ship_reserved(1, "WH-A", 30)

        self.assertEqual(raised.exception.reserved_quantity, Decimal("20.000"))
        self.assertEqual(raised.exception.requested_quantity, Decimal("30"))
        self.assertEqual(inventory.on_hand_quantity, Decimal("100.000"))
        self.assertEqual(inventory.reserved_quantity, Decimal("20.000"))
        self.inventories.save.assert_not_awaited()
        self.movements.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_stock_out_allows_exact_available_quantity(self) -> None:
        inventory = make_inventory(on_hand="100.000", reserved="20.000")
        self.inventories.get_for_update.return_value = inventory

        await self.service.stock_out(1, "WH-A", 80)

        self.assertEqual(inventory.on_hand_quantity, Decimal("20.000"))
        self.assertEqual(inventory.status, InventoryStatus.OUT_OF_STOCK)

    async def test_rejects_nonpositive_quantity_before_starting_transaction(self) -> None:
        for quantity in (0, -1, Decimal("NaN")):
            with self.subTest(quantity=quantity):
                with self.assertRaises(InvalidStockQuantityError):
                    await self.service.stock_in(1, "WH-A", quantity)

        self.assertEqual(self.session.begin_calls, 0)
        self.inventories.get_for_update.assert_not_awaited()

    async def test_missing_inventory_rolls_back_without_movement(self) -> None:
        self.inventories.get_for_update.return_value = None

        with self.assertRaises(InventoryNotFoundError):
            await self.service.stock_out(99, "WH-X", 1)

        self.assertIs(self.session.transaction.exception_type, InventoryNotFoundError)
        self.inventories.save.assert_not_awaited()
        self.movements.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_movement_failure_causes_transaction_rollback(self) -> None:
        inventory = make_inventory()
        self.inventories.get_for_update.return_value = inventory
        self.movements.save.side_effect = RuntimeError("movement write failed")

        with self.assertRaisesRegex(RuntimeError, "movement write failed"):
            await self.service.stock_out(1, "WH-A", 1)

        self.assertIs(self.session.transaction.exception_type, RuntimeError)
        self.inventories.save.assert_awaited_once_with(inventory)
        self.audits.append.assert_not_awaited()

    async def test_audit_failure_aborts_inventory_transaction(self) -> None:
        inventory = make_inventory()
        self.inventories.get_for_update.return_value = inventory
        self.audits.append.side_effect = RuntimeError("audit write failed")

        with self.assertRaisesRegex(RuntimeError, "audit write failed"):
            await self.service.stock_out(1, "WH-A", 1)

        self.assertIs(self.session.transaction.exception_type, RuntimeError)
        self.movements.save.assert_awaited_once()

    async def test_non_system_actor_requires_identifier(self) -> None:
        with self.assertRaises(InvalidInventoryDataError):
            await self.service.stock_in(1, "WH-A", 1, actor_type=ActorType.EMPLOYEE)

        self.assertEqual(self.session.begin_calls, 0)
        self.inventories.get_for_update.assert_not_awaited()

    async def test_invalid_identity_and_reference_are_rejected_before_transaction(
        self,
    ) -> None:
        invalid_calls = (
            self.service.stock_in(0, "WH-A", 1),
            self.service.stock_in(1, "  ", 1),
            self.service.stock_in(1, "WH-A", 1, reference_type="ORDER"),
            self.service.stock_in(1, "WH-A", 1, reference_id=10),
            self.service.stock_in(
                1,
                "WH-A",
                1,
                reference_type="ORDER",
                reference_id=0,
            ),
            self.service.stock_in(1, "WH-A", 1, trace_id="  "),
        )

        for call in invalid_calls:
            with self.assertRaises(InvalidInventoryDataError):
                await call

        self.assertEqual(self.session.begin_calls, 0)
        self.inventories.get_for_update.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
