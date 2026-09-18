import unittest
from unittest.mock import AsyncMock, MagicMock

from app.models.inventory import Inventory
from app.repositories.inventory import InventoryRepository


class InventoryRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_for_update_uses_database_row_lock(self) -> None:
        session = MagicMock()
        session.scalar = AsyncMock(return_value=None)
        repository = InventoryRepository(session)

        await repository.get_for_update(1, "WH-A")

        statement = session.scalar.await_args.args[0]
        self.assertIsNotNone(statement._for_update_arg)

    async def test_save_flushes_without_committing(self) -> None:
        session = MagicMock()
        session.flush = AsyncMock()
        repository = InventoryRepository(session)
        inventory = Inventory(product_id=1, warehouse_code="WH-A")

        result = await repository.save(inventory)

        self.assertIs(result, inventory)
        session.add.assert_called_once_with(inventory)
        session.flush.assert_awaited_once_with()
        session.commit.assert_not_called()
