import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.capabilities.inventory_count import InventoryCountCapability
from app.core.enums import ActorType, TaskType, WarehouseLocationType
from app.core.exceptions import InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.employee import Employee
from app.models.inventory_count_item import InventoryCountItem
from app.models.warehouse_location import WarehouseLocation
from app.services.inventory.counting import InventoryCountService


class FakeSession:
    def __init__(self, active: bool = True) -> None:
        self.active = active

    def in_transaction(self) -> bool:
        return self.active


class InventoryCountServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.items = [
            InventoryCountItem(
                id=11,
                task_id=101,
                product_id=201,
                location_id=301,
                system_quantity=Decimal("10.000"),
            ),
            InventoryCountItem(
                id=12,
                task_id=101,
                product_id=202,
                location_id=301,
                system_quantity=Decimal("5.000"),
            ),
        ]
        self.tasks = MagicMock()
        self.tasks.save_inventory_count_item = AsyncMock(
            side_effect=lambda item: item
        )
        self.locations = MagicMock()
        self.locations.get_for_update = AsyncMock(
            return_value=WarehouseLocation(
                id=301,
                warehouse_id=1,
                code="STORAGE-A",
                location_type=WarehouseLocationType.STORAGE,
                is_active=True,
            )
        )
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = InventoryCountService(
            self.session,  # type: ignore[arg-type]
            self.tasks,
            self.locations,
            self.audits,
        )

    async def test_record_counts_writes_results_without_adjusting_inventory(
        self,
    ) -> None:
        await self.service.record_counts_in_transaction(
            self.items,
            {11: Decimal("9.000"), 12: Decimal("7.000")},
            warehouse_id=1,
            actor_type=ActorType.EMPLOYEE,
            actor_id="23",
            trace_id="trace-count",
        )

        self.assertEqual(self.items[0].counted_quantity, Decimal("9.000"))
        self.assertEqual(self.items[1].counted_quantity, Decimal("7.000"))
        self.assertEqual(self.tasks.save_inventory_count_item.await_count, 2)
        self.assertEqual(self.audits.append.await_count, 2)
        first_audit = self.audits.append.await_args_list[0].args[0]
        self.assertEqual(first_audit.action, "COUNT_INVENTORY")
        self.assertEqual(first_audit.after_data["difference_quantity"], "-1.000")
        self.assertEqual(first_audit.trace_id, "trace-count")

    async def test_record_counts_rejects_wrong_location_and_recount(self) -> None:
        self.locations.get_for_update.return_value.warehouse_id = 2
        with self.assertRaisesRegex(InvalidTaskDataError, "task warehouse"):
            await self.service.record_counts_in_transaction(
                [self.items[0]],
                {11: Decimal("10")},
                warehouse_id=1,
                actor_type=ActorType.EMPLOYEE,
                actor_id="23",
                trace_id="trace-count",
            )

        self.locations.get_for_update.return_value.warehouse_id = 1
        self.items[0].counted_quantity = Decimal("10")
        with self.assertRaisesRegex(InvalidTaskDataError, "already been recorded"):
            await self.service.record_counts_in_transaction(
                [self.items[0]],
                {11: Decimal("10")},
                warehouse_id=1,
                actor_type=ActorType.EMPLOYEE,
                actor_id="23",
                trace_id="trace-count",
            )

    async def test_record_counts_requires_outer_transaction(self) -> None:
        self.session.active = False
        with self.assertRaisesRegex(RuntimeError, "requires an active transaction"):
            await self.service.record_counts_in_transaction(
                self.items,
                {11: Decimal("9"), 12: Decimal("7")},
                warehouse_id=1,
                actor_type=ActorType.EMPLOYEE,
                actor_id="23",
                trace_id="trace-count",
            )


class InventoryCountCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.service = MagicMock()
        self.service.record_counts_in_transaction = AsyncMock()
        self.capability = InventoryCountCapability(self.service)
        self.task = BusinessTask(
            id=101,
            task_no="COUNT-101",
            task_type=TaskType.INVENTORY_COUNT,
            warehouse_id=1,
            assignee_id=23,
        )
        self.item = InventoryCountItem(
            id=11,
            task_id=101,
            product_id=201,
            location_id=301,
            system_quantity=Decimal("10.000"),
        )

    async def test_capability_records_all_count_items(self) -> None:
        validated = self.capability.validate(
            self.task,
            [self.item],
            {
                "results": [
                    {
                        "inventory_count_item_id": 11,
                        "counted_quantity": "9.500",
                    }
                ],
                "remark": "货架复核完成",
            },
        )

        await self.capability.execute(
            self.task,
            Employee(id=23),
            validated,
            "trace-count",
        )

        call = self.service.record_counts_in_transaction.await_args
        self.assertEqual(call.args[0], [self.item])
        self.assertEqual(call.args[1], {11: Decimal("9.500")})
        self.assertEqual(call.kwargs["warehouse_id"], 1)

    async def test_capability_rejects_missing_or_duplicate_results(self) -> None:
        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(self.task, [self.item], {"results": []})

        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(
                self.task,
                [self.item],
                {
                    "results": [
                        {
                            "inventory_count_item_id": 11,
                            "counted_quantity": "10",
                        },
                        {
                            "inventory_count_item_id": 11,
                            "counted_quantity": "10",
                        },
                    ]
                },
            )


if __name__ == "__main__":
    unittest.main()
