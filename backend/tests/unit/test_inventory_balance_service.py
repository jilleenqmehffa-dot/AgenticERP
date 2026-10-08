import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import InventoryStatus
from app.core.exceptions import (
    InsufficientReservedStockError,
    InsufficientStockError,
)
from app.models.inventory import Inventory
from app.services.inventory.balance import InventoryBalanceService


class FakeSession:
    def __init__(self) -> None:
        self.active = False

    def in_transaction(self) -> bool:
        return self.active


class InventoryBalanceServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.inventories = MagicMock()
        self.inventory = Inventory(
            product_id=1,
            warehouse_code="WH-A",
            on_hand_quantity=Decimal("100.000"),
            reserved_quantity=Decimal("20.000"),
            low_stock_threshold=Decimal("50.000"),
            status=InventoryStatus.NORMAL,
        )
        self.inventories.get_for_update = AsyncMock(return_value=self.inventory)
        self.inventories.save = AsyncMock(side_effect=lambda inventory: inventory)
        self.service = InventoryBalanceService(
            self.session,  # type: ignore[arg-type]
            self.inventories,
        )

    async def test_mutation_requires_active_transaction(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "active transaction"):
            await self.service.reserve_in_transaction(1, "WH-A", 1)

        self.inventories.get_for_update.assert_not_awaited()

    async def test_reserve_and_release_are_the_balance_write_boundary(self) -> None:
        self.session.active = True

        reserved = await self.service.reserve_in_transaction(1, "WH-A", 50)

        self.assertEqual(reserved.before_data["reserved_quantity"], "20.000")
        self.assertEqual(self.inventory.reserved_quantity, Decimal("70.000"))
        self.assertEqual(self.inventory.status, InventoryStatus.LOW_STOCK)

        released = await self.service.release_reserved_in_transaction(
            1,
            "WH-A",
            30,
        )

        self.assertEqual(released.before_data["reserved_quantity"], "70.000")
        self.assertEqual(self.inventory.reserved_quantity, Decimal("40.000"))
        self.assertEqual(self.inventory.status, InventoryStatus.NORMAL)

    async def test_rejects_unavailable_and_unreserved_quantities(self) -> None:
        self.session.active = True

        with self.assertRaises(InsufficientStockError):
            await self.service.decrease_available_in_transaction(1, "WH-A", 81)

        with self.assertRaises(InsufficientReservedStockError):
            await self.service.ship_reserved_in_transaction(1, "WH-A", 21)

        self.inventories.save.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
