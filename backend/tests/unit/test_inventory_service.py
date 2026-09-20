import json
import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import ActorType, InventoryStatus, MovementType
from app.core.exceptions import (
    InsufficientStockError,
    InvalidStockQuantityError,
    InventoryNotFoundError,
)
from app.models.inventory import Inventory
from app.services.inventory import InventoryService


class FakeTransaction:
    def __init__(self) -> None:
        self.exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        self.exception_type = exception_type
        return False


class FakeSession:
    def __init__(self) -> None:
        self.transaction = FakeTransaction()
        self.begin_calls = 0

    def begin(self) -> FakeTransaction:
        self.begin_calls += 1
        return self.transaction


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


class InventoryServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.inventories = MagicMock()
        self.inventories.get_for_update = AsyncMock()
        self.inventories.save = AsyncMock(side_effect=lambda inventory: inventory)
        self.movements = MagicMock()
        self.movements.save = AsyncMock(side_effect=lambda movement: movement)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = InventoryService(
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
        with self.assertRaises(ValueError):
            await self.service.stock_in(1, "WH-A", 1, actor_type=ActorType.EMPLOYEE)

        self.assertEqual(self.session.begin_calls, 0)
        self.inventories.get_for_update.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
