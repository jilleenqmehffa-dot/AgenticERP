import unittest

from sqlalchemy import Boolean, DateTime

from app.db.base import Base
from app.models.employee import Employee
from app.models.user_account import UserAccount


class UserAccountModelTests(unittest.TestCase):
    def test_required_columns_and_unique_account_identity(self) -> None:
        table = UserAccount.__table__
        columns = table.columns

        self.assertIn("user_accounts", Base.metadata.tables)
        for name in ("employee_id", "username", "password_hash", "is_active"):
            with self.subTest(column=name):
                self.assertFalse(columns[name].nullable)

        self.assertTrue(columns.employee_id.unique)
        self.assertTrue(columns.username.unique)
        self.assertEqual(
            next(iter(columns.employee_id.foreign_keys)).target_fullname,
            "employees.id",
        )
        self.assertNotIn("password", columns)

    def test_defaults_and_optional_last_login(self) -> None:
        columns = UserAccount.__table__.columns

        self.assertIsInstance(columns.is_active.type, Boolean)
        self.assertIs(columns.is_active.default.arg, True)
        self.assertIsInstance(columns.created_at.type, DateTime)
        self.assertIsInstance(columns.updated_at.type, DateTime)
        self.assertTrue(columns.last_login_at.nullable)
        self.assertIsInstance(columns.last_login_at.type, DateTime)
        self.assertTrue(columns.last_login_at.type.timezone)

    def test_employee_relation_is_one_to_one(self) -> None:
        self.assertFalse(Employee.user_account.property.uselist)
        self.assertFalse(UserAccount.employee.property.uselist)

        employee = Employee(id=1)
        account = UserAccount(username="operator1", password_hash="stored-hash")
        account.employee = employee

        self.assertIs(employee.user_account, account)


if __name__ == "__main__":
    unittest.main()
