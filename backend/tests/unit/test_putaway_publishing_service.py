import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import (
    ActorType,
    DispatchRequestStatus,
    EmployeeStatus,
    StockStatus,
    TaskStatus,
    TaskType,
    WarehouseLocationType,
)
from app.core.exceptions import InvalidTaskDataError
from app.models.employee import Employee
from app.models.inventory_bucket import InventoryBucket
from app.models.putaway_dispatch_request import PutawayDispatchRequest
from app.models.role import Role
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation
from app.services.inbound.putaway_publishing import PutawayPublishingService


class FakeTransaction:
    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


class FakeSession:
    def begin(self) -> FakeTransaction:
        return FakeTransaction()


class PutawayPublishingServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        source = InventoryBucket(
            id=401,
            product_id=301,
            warehouse_code="WH-A",
            location_code="RECEIVING-A",
            lot_no="LOT-1",
            stock_status=StockStatus.PENDING_PUTAWAY,
            quantity=Decimal("38.000"),
        )
        from_location = WarehouseLocation(
            id=11,
            warehouse_id=1,
            code="RECEIVING-A",
            location_type=WarehouseLocationType.RECEIVING,
            is_active=True,
        )
        from_location.warehouse = Warehouse(id=1, code="WH-A", name="Warehouse A")
        self.request = PutawayDispatchRequest(
            id=77,
            inspection_id=501,
            source_bucket_id=401,
            warehouse_id=1,
            from_location_id=11,
            required_location_type=WarehouseLocationType.STORAGE,
            target_stock_status=StockStatus.AVAILABLE,
            planned_quantity=Decimal("38.000"),
            generation_key="PUTAWAY:501:PENDING_PUTAWAY",
            status=DispatchRequestStatus.PENDING,
        )
        self.request.source_bucket = source
        self.request.from_location = from_location
        self.dispatches = MagicMock()
        self.dispatches.get_for_update = AsyncMock(return_value=self.request)
        self.dispatches.save = AsyncMock(side_effect=lambda request: request)
        self.tasks = MagicMock()

        async def save_task(task: object) -> object:
            task.id = 900
            return task

        self.tasks.save = AsyncMock(side_effect=save_task)
        self.assignee = Employee(id=23, status=EmployeeStatus.ACTIVE)
        self.manager = Employee(id=99, status=EmployeeStatus.ACTIVE)
        self.manager.role = Role(id=2, code="MANAGER", name="Manager")
        self.employees = MagicMock()
        self.employees.get_for_update = AsyncMock(return_value=self.assignee)
        self.employees.get_with_role_for_update = AsyncMock(return_value=self.manager)
        self.target = WarehouseLocation(
            id=12,
            warehouse_id=1,
            code="STORAGE-A",
            location_type=WarehouseLocationType.STORAGE,
            is_active=True,
        )
        self.locations = MagicMock()
        self.locations.get_for_update = AsyncMock(return_value=self.target)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = PutawayPublishingService(
            self.session,  # type: ignore[arg-type]
            self.dispatches,
            self.tasks,
            self.employees,
            self.locations,
            self.audits,
        )

    async def test_agent_can_publish_with_explicit_assignee_and_location(self) -> None:
        task = await self.service.publish_putaway_request(
            77,
            23,
            12,
            ActorType.AGENT,
            "planner-agent",
            "trace-publish",
        )

        self.assertEqual(task.task_no, "PUTAWAY-77")
        self.assertEqual(task.task_type, TaskType.PUTAWAY)
        self.assertEqual(task.status, TaskStatus.ASSIGNED)
        self.assertEqual(task.assignee_id, 23)
        self.assertEqual(task.source_type, "PUTAWAY_DISPATCH")
        self.assertEqual(task.created_by_type, ActorType.AGENT)
        self.assertEqual(task.created_by_id, "planner-agent")
        self.assertEqual(task.items[0].to_location_id, 12)
        self.assertEqual(task.items[0].source_bucket_id, 401)
        self.assertEqual(self.request.status, DispatchRequestStatus.PUBLISHED)
        self.assertEqual(self.request.published_task_id, 900)
        self.assertEqual(self.request.published_by_type, ActorType.AGENT)

    async def test_manager_employee_can_publish(self) -> None:
        task = await self.service.publish_putaway_request(
            77,
            23,
            12,
            ActorType.EMPLOYEE,
            "99",
            "trace-manager",
        )

        self.assertEqual(task.created_by_id, "99")
        self.employees.get_with_role_for_update.assert_awaited_once_with(99)

    async def test_non_manager_employee_and_system_cannot_publish(self) -> None:
        self.manager.role = Role(id=3, code="OPERATOR", name="Operator")
        with self.assertRaisesRegex(InvalidTaskDataError, "MANAGER"):
            await self.service.publish_putaway_request(
                77, 23, 12, ActorType.EMPLOYEE, "99", "trace-operator"
            )

        with self.assertRaisesRegex(InvalidTaskDataError, "SYSTEM"):
            await self.service.publish_putaway_request(
                77, 23, 12, ActorType.SYSTEM, "SYSTEM", "trace-system"
            )

    async def test_wrong_warehouse_or_location_type_is_rejected(self) -> None:
        self.target.warehouse_id = 2
        with self.assertRaisesRegex(InvalidTaskDataError, "target location"):
            await self.service.publish_putaway_request(
                77, 23, 12, ActorType.AGENT, "agent", "trace-wrong-warehouse"
            )

        self.target.warehouse_id = 1
        self.target.location_type = WarehouseLocationType.QUARANTINE
        with self.assertRaisesRegex(InvalidTaskDataError, "target location"):
            await self.service.publish_putaway_request(
                77, 23, 12, ActorType.AGENT, "agent", "trace-wrong-type"
            )

    async def test_repeated_publish_returns_original_task(self) -> None:
        original = await self.service.publish_putaway_request(
            77, 23, 12, ActorType.AGENT, "agent", "trace-first"
        )
        self.tasks.save.reset_mock()
        self.audits.append.reset_mock()

        repeated = await self.service.publish_putaway_request(
            77, 23, 12, ActorType.AGENT, "agent", "trace-repeat"
        )

        self.assertIs(repeated, original)
        self.tasks.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
