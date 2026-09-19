import unittest

from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import JSONB

from app.core.enums import ActorType, TaskStatus, TaskType
from app.models.business_task import BusinessTask
from app.models.employee import Employee


class BusinessTaskV2ModelTests(unittest.TestCase):
    def test_task_enums_contain_only_v2_values(self) -> None:
        self.assertEqual(set(TaskType), {TaskType.STOCK_IN, TaskType.STOCK_OUT})
        self.assertEqual(
            set(TaskStatus),
            {TaskStatus.PENDING, TaskStatus.COMPLETED, TaskStatus.CANCELLED},
        )

    def test_required_columns_and_defaults(self) -> None:
        columns = BusinessTask.__table__.columns

        for name in (
            "task_no",
            "task_type",
            "status",
            "assigned_employee_id",
            "planned_data",
            "created_by_type",
        ):
            with self.subTest(column=name):
                self.assertFalse(columns[name].nullable)

        self.assertTrue(columns.task_no.unique)
        self.assertEqual(columns.status.server_default.arg, TaskStatus.PENDING.value)
        self.assertIsInstance(columns.task_type.type, Enum)
        self.assertIsInstance(columns.status.type, Enum)
        self.assertIsInstance(columns.created_by_type.type, Enum)
        self.assertEqual(columns.created_by_type.type.enum_class, ActorType)

    def test_optional_columns_and_jsonb(self) -> None:
        columns = BusinessTask.__table__.columns

        for name in (
            "source_type",
            "source_id",
            "actual_data",
            "exception_reason",
            "cancel_reason",
            "created_by_id",
            "completed_at",
            "cancelled_at",
        ):
            with self.subTest(column=name):
                self.assertTrue(columns[name].nullable)

        self.assertIsInstance(columns.planned_data.type, JSONB)
        self.assertIsInstance(columns.actual_data.type, JSONB)
        self.assertNotIn("created_by", columns)
        self.assertNotIn("started_at", columns)

    def test_employee_relationship_uses_required_foreign_key(self) -> None:
        column = BusinessTask.__table__.columns.assigned_employee_id

        self.assertEqual(next(iter(column.foreign_keys)).target_fullname, "employees.id")
        self.assertFalse(BusinessTask.assigned_employee.property.uselist)
        self.assertTrue(Employee.assigned_tasks.property.uselist)


if __name__ == "__main__":
    unittest.main()
