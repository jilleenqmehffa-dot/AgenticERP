import unittest
from datetime import date, datetime, timezone
from decimal import Decimal

from pydantic import ValidationError

from app.core.enums import PayableStatus, ReceivableStatus
from app.models.account_payable import AccountPayable
from app.models.account_receivable import AccountReceivable
from app.schemas.account_payable import AccountPayableCreate, AccountPayableRead
from app.schemas.account_receivable import (
    AccountReceivableCreate,
    AccountReceivableRead,
)


class AccountModelTests(unittest.TestCase):
    def test_receivable_calculates_outstanding_amount(self) -> None:
        receivable = AccountReceivable(
            sales_order_id=1,
            customer_name="Customer A",
            amount=Decimal("1000.00"),
            paid_amount=Decimal("250.00"),
            due_date=date(2026, 10, 1),
            status=ReceivableStatus.PARTIALLY_PAID,
        )

        self.assertEqual(receivable.outstanding_amount, Decimal("750.00"))

    def test_payable_calculates_outstanding_amount(self) -> None:
        payable = AccountPayable(
            reference_no="PO-1001",
            supplier_name="Supplier A",
            amount=Decimal("800.00"),
            paid_amount=Decimal("300.00"),
            due_date=date(2026, 10, 1),
            status=PayableStatus.PARTIALLY_PAID,
        )

        self.assertEqual(payable.outstanding_amount, Decimal("500.00"))

    def test_receivable_schema_rejects_paid_amount_above_amount(self) -> None:
        with self.assertRaises(ValidationError):
            AccountReceivableCreate(
                sales_order_id=1,
                customer_name="Customer A",
                amount=Decimal("100.00"),
                paid_amount=Decimal("100.01"),
                due_date=date(2026, 10, 1),
            )

    def test_payable_schema_rejects_paid_amount_above_amount(self) -> None:
        with self.assertRaises(ValidationError):
            AccountPayableCreate(
                reference_no="PO-1001",
                supplier_name="Supplier A",
                amount=Decimal("100.00"),
                paid_amount=Decimal("100.01"),
                due_date=date(2026, 10, 1),
            )

    def test_read_schemas_expose_outstanding_amount(self) -> None:
        now = datetime.now(timezone.utc)
        receivable = AccountReceivable(
            id=1,
            sales_order_id=10,
            customer_name="Customer A",
            amount=Decimal("100.00"),
            paid_amount=Decimal("30.00"),
            due_date=date(2026, 10, 1),
            status=ReceivableStatus.PARTIALLY_PAID,
            created_at=now,
            updated_at=now,
        )
        payable = AccountPayable(
            id=2,
            reference_no="PO-1001",
            supplier_name="Supplier A",
            amount=Decimal("90.00"),
            paid_amount=Decimal("20.00"),
            due_date=date(2026, 10, 1),
            status=PayableStatus.PARTIALLY_PAID,
            created_at=now,
            updated_at=now,
        )

        receivable_read = AccountReceivableRead.model_validate(receivable)
        payable_read = AccountPayableRead.model_validate(payable)

        self.assertEqual(receivable_read.outstanding_amount, Decimal("70.00"))
        self.assertEqual(payable_read.outstanding_amount, Decimal("70.00"))


if __name__ == "__main__":
    unittest.main()
