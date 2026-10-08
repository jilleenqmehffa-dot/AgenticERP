import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.capabilities.putaway import PutawayCapability
from app.core.enums import StockStatus, TaskType, WarehouseLocationType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.inventory_bucket import InventoryBucket
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation


class PutawayCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.bucket_service = MagicMock()
        self.bucket_service.move_in_transaction = AsyncMock()
        self.inventory_service = MagicMock()
        self.inventory_service.stock_in_in_transaction = AsyncMock()
        self.capability = PutawayCapability(
            self.bucket_service,
            self.inventory_service,
        )
        self.task = BusinessTask(
            id=1001,
            task_no="PUTAWAY-501-PENDING_PUTAWAY",
            task_type=TaskType.PUTAWAY,
            warehouse_id=1,
            assignee_id=23,
        )
        self.task.warehouse = Warehouse(id=1, code="WH-A", name="Warehouse A")
        source_location = WarehouseLocation(
            id=11,
            warehouse_id=1,
            code="RECEIVING-A",
            location_type=WarehouseLocationType.RECEIVING,
            is_active=True,
        )
        target_location = WarehouseLocation(
            id=12,
            warehouse_id=1,
            code="STORAGE-A",
            location_type=WarehouseLocationType.STORAGE,
            is_active=True,
        )
        source_bucket = InventoryBucket(
            id=401,
            product_id=301,
            warehouse_code="WH-A",
            location_code="RECEIVING-A",
            lot_no="LOT-1",
            stock_status=StockStatus.PENDING_PUTAWAY,
            quantity=Decimal("38.000"),
        )
        self.item = BusinessTaskItem(
            id=101,
            task_id=1001,
            product_id=301,
            from_location_id=11,
            to_location_id=12,
            source_bucket_id=401,
            target_stock_status=StockStatus.AVAILABLE,
            planned_quantity=Decimal("38.000"),
        )
        self.item.from_location = source_location
        self.item.to_location = target_location
        self.item.source_bucket = source_bucket
        self.employee = Employee(id=23)

    async def test_accepted_goods_move_and_become_sellable_inventory(self) -> None:
        validated = self.capability.validate(
            self.task,
            [self.item],
            {"actual_quantity": "38.000"},
        )

        await self.capability.execute(
            self.task,
            self.employee,
            validated,
            "trace-putaway",
        )

        move = self.bucket_service.move_in_transaction.await_args
        self.assertEqual(move.kwargs["from_status"], StockStatus.PENDING_PUTAWAY)
        self.assertEqual(move.kwargs["to_status"], StockStatus.AVAILABLE)
        self.assertEqual(move.kwargs["to_location_code"], "STORAGE-A")
        self.inventory_service.stock_in_in_transaction.assert_awaited_once()
        self.assertEqual(self.item.actual_quantity, Decimal("38.000"))

    async def test_defective_goods_move_without_becoming_sellable(self) -> None:
        self.item.source_bucket.stock_status = StockStatus.DEFECTIVE
        self.item.target_stock_status = StockStatus.DEFECTIVE
        self.item.to_location.location_type = WarehouseLocationType.QUARANTINE
        self.item.to_location.code = "QUARANTINE-A"

        validated = self.capability.validate(
            self.task,
            [self.item],
            {"actual_quantity": "38.000"},
        )
        await self.capability.execute(
            self.task,
            self.employee,
            validated,
            "trace-putaway",
        )

        move = self.bucket_service.move_in_transaction.await_args
        self.assertEqual(move.kwargs["to_status"], StockStatus.DEFECTIVE)
        self.assertEqual(move.kwargs["to_location_code"], "QUARANTINE-A")
        self.inventory_service.stock_in_in_transaction.assert_not_awaited()

    def test_rejects_quantity_or_inventory_identity_mismatch(self) -> None:
        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(
                self.task,
                [self.item],
                {"actual_quantity": "37.000"},
            )

        self.item.source_bucket.product_id = 999
        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(
                self.task,
                [self.item],
                {"actual_quantity": "38.000"},
            )


if __name__ == "__main__":
    unittest.main()
