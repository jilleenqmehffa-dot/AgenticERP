import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.capabilities.receiving import ReceiveCapability
from app.core.enums import ActorType, ReceiptStatus, TaskType
from app.core.exceptions import InvalidReceivingDataError, InvalidTaskDataError
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.inbound_receipt import InboundReceipt
from app.models.inbound_receipt_item import InboundReceiptItem
from app.services.receiving import ReceivingService


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self.session = session

    async def __aenter__(self) -> "FakeTransaction":
        self.session.active = True
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        self.session.active = False
        return False


class FakeSession:
    def __init__(self) -> None:
        self.active = False
        self.begin_calls = 0

    def begin(self) -> FakeTransaction:
        self.begin_calls += 1
        return FakeTransaction(self)

    def in_transaction(self) -> bool:
        return self.active


class ReceivingServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.receipt = InboundReceipt(
            id=201,
            receipt_no="RCV-201",
            warehouse_code="WH-A",
            status=ReceiptStatus.PENDING_RECEIPT,
        )
        self.item = InboundReceiptItem(
            id=101,
            inbound_receipt_id=201,
            product_id=301,
            expected_quantity=Decimal("100.000"),
            received_quantity=Decimal("0.000"),
            accepted_quantity=Decimal("0.000"),
            defective_quantity=Decimal("0.000"),
            quarantined_quantity=Decimal("0.000"),
            rejected_quantity=Decimal("0.000"),
        )
        self.receipts = MagicMock()
        self.receipts.get_item = AsyncMock(return_value=self.item)
        self.receipts.get_for_update = AsyncMock(return_value=self.receipt)
        self.receipts.get_items_for_update = AsyncMock(return_value=[self.item])
        self.receipts.save = AsyncMock(side_effect=lambda receipt: receipt)
        self.receipts.save_item = AsyncMock(side_effect=lambda item: item)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = ReceivingService(
            self.session,  # type: ignore[arg-type]
            self.receipts,
            self.audits,
        )

    async def test_employee_quantities_are_saved_and_receipt_is_inspected(self) -> None:
        result = await self.service.receive_and_inspect(
            101,
            received_quantity=Decimal("100.000"),
            accepted_quantity=Decimal("95.000"),
            defective_quantity=Decimal("5.000"),
            expected_product_id=301,
            actor_type=ActorType.EMPLOYEE,
            actor_id="23",
            trace_id="trace-receive",
        )

        self.assertIs(result, self.item)
        self.assertEqual(self.item.received_quantity, Decimal("100.000"))
        self.assertEqual(self.item.accepted_quantity, Decimal("95.000"))
        self.assertEqual(self.item.defective_quantity, Decimal("5.000"))
        self.assertEqual(self.receipt.status, ReceiptStatus.INSPECTED)
        self.assertIsNotNone(self.receipt.received_at)
        self.assertIsNotNone(self.receipt.inspected_at)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "RECEIVE_AND_INSPECT_GOODS")
        self.assertEqual(audit.trace_id, "trace-receive")

    async def test_partial_receipt_remains_receiving(self) -> None:
        await self.service.receive_and_inspect(
            101,
            received_quantity=40,
            accepted_quantity=38,
            defective_quantity=2,
            expected_product_id=301,
        )

        self.assertEqual(self.receipt.status, ReceiptStatus.RECEIVING)
        self.assertIsNone(self.receipt.received_at)
        self.assertIsNone(self.receipt.inspected_at)

    async def test_quality_total_and_item_remainder_are_enforced(self) -> None:
        with self.assertRaises(InvalidReceivingDataError):
            await self.service.receive_and_inspect(
                101,
                received_quantity=100,
                accepted_quantity=90,
                defective_quantity=5,
                expected_product_id=301,
            )

        self.item.received_quantity = Decimal("90.000")
        with self.assertRaises(InvalidReceivingDataError):
            await self.service.receive_and_inspect(
                101,
                received_quantity=20,
                accepted_quantity=20,
                defective_quantity=0,
                expected_product_id=301,
            )


class ReceiveCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.receiving = MagicMock()
        self.receiving.receive_and_inspect_in_transaction = AsyncMock()
        self.capability = ReceiveCapability(self.receiving)
        self.task = BusinessTask(
            id=1,
            task_no="RECEIVE-1",
            task_type=TaskType.RECEIVE,
            warehouse_id=1,
            assignee_id=23,
            source_type="INBOUND_RECEIPT_ITEM",
            source_id=101,
        )
        self.item = BusinessTaskItem(
            id=11,
            task_id=1,
            product_id=301,
            planned_quantity=Decimal("100.000"),
        )
        self.employee = Employee(id=23)
        self.actual_data = {
            "received_quantity": "100.000",
            "accepted_quantity": "95.000",
            "defective_quantity": "5.000",
            "quarantined_quantity": "0.000",
            "rejected_quantity": "0.000",
        }

    async def test_execute_passes_employee_result_to_receiving_service(self) -> None:
        validated = self.capability.validate(
            self.task,
            [self.item],
            self.actual_data,
        )

        await self.capability.execute(
            self.task,
            self.employee,
            validated,
            "trace-receive",
        )

        call = self.receiving.receive_and_inspect_in_transaction.await_args
        self.assertEqual(call.args, (101,))
        self.assertEqual(call.kwargs["received_quantity"], Decimal("100.000"))
        self.assertEqual(call.kwargs["accepted_quantity"], Decimal("95.000"))
        self.assertEqual(call.kwargs["defective_quantity"], Decimal("5.000"))
        self.assertEqual(self.item.actual_quantity, Decimal("100.000"))

    async def test_validate_rejects_wrong_source_and_inconsistent_total(self) -> None:
        self.task.source_type = "INBOUND_RECEIPT"
        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(self.task, [self.item], self.actual_data)

        self.task.source_type = "INBOUND_RECEIPT_ITEM"
        invalid = {**self.actual_data, "defective_quantity": "4.000"}
        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(self.task, [self.item], invalid)


if __name__ == "__main__":
    unittest.main()
