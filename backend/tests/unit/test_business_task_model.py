import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from app.core.enums import TaskStatus, TaskType
from app.models.business_task import BusinessTask
from app.schemas.business_task import (
    BusinessTaskAssign,
    BusinessTaskCreate,
    BusinessTaskRead,
    BusinessTaskUpdate,
)


class BusinessTaskModelTests(unittest.TestCase):
    def test_create_keeps_planned_data_and_defaults_are_modelled(self) -> None:
        task = BusinessTaskCreate(
            task_no="TASK-001",
            task_type=TaskType.STOCK_OUT,
            assigned_employee_id=1,
            source_type="SALES_ORDER",
            source_id=1001,
            planned_data={
                "product_id": 1,
                "warehouse_code": "A",
                "quantity": 50,
            },
            created_by="SYSTEM",
        )

        self.assertEqual(task.planned_data["quantity"], 50)
        self.assertNotIn("actual_data", task.model_fields_set)

    def test_create_rejects_status_from_normal_crud(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessTaskCreate(
                task_no="TASK-001",
                task_type=TaskType.STOCK_IN,
                planned_data={"quantity": 50},
                created_by="SYSTEM",
                status=TaskStatus.COMPLETED,
            )

    def test_update_rejects_status_and_actual_data(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessTaskUpdate(status=TaskStatus.COMPLETED)
        with self.assertRaises(ValidationError):
            BusinessTaskUpdate(actual_data={"quantity": 40})

    def test_source_fields_must_be_provided_together(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessTaskCreate(
                task_no="TASK-001",
                task_type=TaskType.STOCK_OUT,
                source_type="SALES_ORDER",
                planned_data={"quantity": 50},
                created_by="SYSTEM",
            )
        with self.assertRaises(ValidationError):
            BusinessTaskUpdate(source_id=1001)

    def test_assignment_requires_valid_identifier_shape(self) -> None:
        with self.assertRaises(ValidationError):
            BusinessTaskAssign(assigned_employee_id=0)

    def test_read_keeps_planned_and_actual_data_separate(self) -> None:
        now = datetime.now(timezone.utc)
        task = BusinessTask(
            id=1,
            task_no="TASK-001",
            task_type=TaskType.STOCK_OUT,
            status=TaskStatus.COMPLETED,
            assigned_employee_id=1,
            source_type="SALES_ORDER",
            source_id=1001,
            planned_data={"quantity": 50},
            actual_data={"quantity": 40},
            exception_reason="10 units damaged",
            created_by="SYSTEM",
            created_at=now,
            started_at=now,
            completed_at=now,
            updated_at=now,
        )

        result = BusinessTaskRead.model_validate(task)

        self.assertEqual(result.planned_data, {"quantity": 50})
        self.assertEqual(result.actual_data, {"quantity": 40})
        self.assertEqual(result.exception_reason, "10 units damaged")


if __name__ == "__main__":
    unittest.main()
