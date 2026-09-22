import unittest
from datetime import datetime, timezone
from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import Computed, Enum

from app.core.enums import ActorType, TaskStatus, TaskType
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.inventory_count_item import InventoryCountItem
from app.schemas.business_task import (
    BusinessTaskAssign,
    BusinessTaskCreate,
    BusinessTaskRead,
    BusinessTaskUpdate,
)


class BusinessTaskModelTests(unittest.TestCase):
    def test_task_enums_contain_exact_supported_values(self) -> None:
        self.assertEqual(
            set(TaskType),
            {
                TaskType.RECEIVE,
                TaskType.PUTAWAY,
                TaskType.PICK,
                TaskType.PACK,
                TaskType.STOCK_IN,
                TaskType.STOCK_OUT,
                TaskType.TRANSFER,
                TaskType.INVENTORY_COUNT,
            },
        )
        self.assertEqual(
            set(TaskStatus),
            {
                TaskStatus.PENDING,
                TaskStatus.IN_PROGRESS,
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            },
        )

    def test_required_columns_and_foreign_keys(self) -> None:
        columns = BusinessTask.__table__.columns

        for name in (
            "task_no",
            "task_type",
            "status",
            "warehouse_id",
            "assignee_id",
            "created_by_type",
        ):
            with self.subTest(column=name):
                self.assertFalse(columns[name].nullable)

        self.assertTrue(columns.task_no.unique)
        self.assertEqual(columns.status.server_default.arg, TaskStatus.PENDING.value)
        self.assertIsInstance(columns.task_type.type, Enum)
        self.assertEqual(
            next(iter(columns.warehouse_id.foreign_keys)).target_fullname,
            "warehouses.id",
        )
        self.assertEqual(
            next(iter(columns.assignee_id.foreign_keys)).target_fullname,
            "employees.id",
        )

    def test_task_uses_structured_items_instead_of_jsonb(self) -> None:
        columns = BusinessTask.__table__.columns

        self.assertNotIn("planned_data", columns)
        self.assertNotIn("actual_data", columns)
        self.assertNotIn("exception_reason", columns)
        self.assertNotIn("cancel_reason", columns)
        self.assertIn("reason", columns)
        self.assertTrue(BusinessTask.items.property.uselist)
        self.assertTrue(BusinessTask.inventory_count_items.property.uselist)

    def test_create_schema_accepts_structured_item(self) -> None:
        task = BusinessTaskCreate(
            task_no="TASK-001",
            task_type=TaskType.STOCK_OUT,
            warehouse_id=1,
            assignee_id=2,
            source_type="SALES_ORDER",
            source_id=1001,
            reason="sales shipment",
            created_by_type=ActorType.SYSTEM,
            items=[
                {
                    "product_id": 10,
                    "from_location_id": 20,
                    "planned_quantity": "50.000",
                }
            ],
        )

        self.assertEqual(task.items[0].planned_quantity, Decimal("50.000"))
        self.assertNotIn("status", task.model_fields_set)

    def test_normal_crud_cannot_write_execution_fields(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessTaskCreate(
                task_no="TASK-001",
                task_type=TaskType.PICK,
                warehouse_id=1,
                assignee_id=2,
                created_by_type=ActorType.SYSTEM,
                status=TaskStatus.COMPLETED,
            )
        with self.assertRaises(ValidationError):
            BusinessTaskUpdate(status=TaskStatus.COMPLETED)
        with self.assertRaises(ValidationError):
            BusinessTaskUpdate(actual_quantity=Decimal("1"))

    def test_source_fields_must_be_provided_together(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessTaskCreate(
                task_no="TASK-001",
                task_type=TaskType.RECEIVE,
                warehouse_id=1,
                assignee_id=2,
                source_type="PURCHASE_ORDER",
                created_by_type=ActorType.SYSTEM,
            )
        with self.assertRaises(ValidationError):
            BusinessTaskUpdate(source_id=1001)

    def test_assignment_requires_positive_assignee(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessTaskAssign(assignee_id=0)
        with self.assertRaises(ValidationError):
            BusinessTaskUpdate(assignee_id=None)

    def test_read_schema_exposes_items_and_reason(self) -> None:
        now = datetime.now(timezone.utc)
        item = BusinessTaskItem(
            id=11,
            task_id=1,
            product_id=10,
            from_location_id=20,
            to_location_id=None,
            planned_quantity=Decimal("50"),
            actual_quantity=Decimal("40"),
        )
        task = BusinessTask(
            id=1,
            task_no="TASK-001",
            task_type=TaskType.STOCK_OUT,
            status=TaskStatus.COMPLETED,
            warehouse_id=1,
            assignee_id=2,
            source_type="SALES_ORDER",
            source_id=1001,
            reason="10 units damaged",
            created_by_type=ActorType.SYSTEM,
            created_by_id=None,
            created_at=now,
            started_at=now,
            completed_at=now,
            cancelled_at=None,
            failed_at=None,
            updated_at=now,
            items=[item],
            inventory_count_items=[],
        )

        result = BusinessTaskRead.model_validate(task)

        self.assertEqual(result.reason, "10 units damaged")
        self.assertEqual(result.items[0].actual_quantity, Decimal("40"))

    def test_inventory_count_difference_is_database_computed(self) -> None:
        column = InventoryCountItem.__table__.columns.difference_quantity

        self.assertIsInstance(column.computed, Computed)
        self.assertEqual(
            str(column.computed.sqltext),
            "counted_quantity - system_quantity",
        )

    def test_task_item_foreign_keys_and_indexes(self) -> None:
        columns = BusinessTaskItem.__table__.columns

        self.assertTrue(columns.task_id.index)
        self.assertTrue(columns.product_id.index)
        self.assertEqual(
            next(iter(columns.task_id.foreign_keys)).target_fullname,
            "business_tasks.id",
        )
        self.assertEqual(
            next(iter(columns.from_location_id.foreign_keys)).target_fullname,
            "warehouse_locations.id",
        )
        self.assertEqual(
            next(iter(columns.to_location_id.foreign_keys)).target_fullname,
            "warehouse_locations.id",
        )

    def test_inventory_count_item_has_dedicated_task_relationship(self) -> None:
        columns = InventoryCountItem.__table__.columns

        self.assertTrue(columns.task_id.index)
        self.assertFalse(InventoryCountItem.task.property.uselist)
        self.assertEqual(
            next(iter(columns.location_id.foreign_keys)).target_fullname,
            "warehouse_locations.id",
        )

    def test_employee_relationship_uses_assignee_foreign_key(self) -> None:
        self.assertFalse(BusinessTask.assignee.property.uselist)
        self.assertTrue(Employee.assigned_tasks.property.uselist)


if __name__ == "__main__":
    unittest.main()
