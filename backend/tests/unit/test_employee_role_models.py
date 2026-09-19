import unittest
from datetime import datetime, timezone

from pydantic import ValidationError

from app.core.enums import EmployeeStatus
from app.models.employee import Employee
from app.models.role import Role
from app.schemas.employee import EmployeeCreate, EmployeeRead


class EmployeeRoleModelTests(unittest.TestCase):
    def test_employee_defaults_to_active(self) -> None:
        employee = EmployeeCreate(
            employee_no="EMP-001",
            name="Employee A",
            role_id=1,
            department="Warehouse",
        )

        self.assertEqual(employee.status, EmployeeStatus.ACTIVE)

    def test_employee_requires_positive_role_id(self) -> None:
        with self.assertRaises(ValidationError):
            EmployeeCreate(
                employee_no="EMP-001",
                name="Employee A",
                role_id=0,
                department="Warehouse",
            )

    def test_employee_read_exposes_role(self) -> None:
        now = datetime.now(timezone.utc)
        role = Role(
            id=1,
            code="WAREHOUSE_OPERATOR",
            name="Warehouse operator",
            description="Handles warehouse tasks",
            created_at=now,
            updated_at=now,
        )
        employee = Employee(
            id=1,
            employee_no="EMP-001",
            name="Employee A",
            role_id=1,
            department="Warehouse",
            status=EmployeeStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            role=role,
        )

        result = EmployeeRead.model_validate(employee)

        self.assertEqual(result.employee_no, "EMP-001")
        self.assertEqual(result.role.code, "WAREHOUSE_OPERATOR")

    def test_role_employee_relationship_is_one_to_many(self) -> None:
        self.assertTrue(Role.employees.property.uselist)
        self.assertFalse(Employee.role.property.uselist)


if __name__ == "__main__":
    unittest.main()
