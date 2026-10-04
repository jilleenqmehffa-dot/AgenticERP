import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import DispatchRequestStatus, ReceiptStatus, StockStatus
from app.core.enums import TaskStatus, TaskType, WarehouseLocationType
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.inbound_receipt import InboundReceipt
from app.models.inbound_receipt_item import InboundReceiptItem
from app.models.putaway_dispatch_request import PutawayDispatchRequest
from app.models.receipt_inspection import ReceiptInspection
from app.services.inbound_completion import InboundCompletionService


class FakeSession:
    def in_transaction(self) -> bool:
        return True


class InboundCompletionServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.receipt = InboundReceipt(
            id=201,
            receipt_no="RCV-201",
            warehouse_code="WH-A",
            status=ReceiptStatus.INSPECTED,
        )
        self.item1 = self._item(101, 201, 301, "10", "7", "2", "0", "1")
        self.item2 = self._item(102, 201, 302, "5", "0", "0", "3", "2")
        self.inspection1 = self._inspection(501, 101, "10", "7", "2", "0", "1")
        self.inspection2 = self._inspection(502, 102, "5", "0", "0", "3", "2")
        self.receipts = MagicMock()
        self.receipts.get_for_update = AsyncMock(return_value=self.receipt)
        self.receipts.get_items_for_update = AsyncMock(
            return_value=[self.item1, self.item2]
        )
        self.receipts.get_item = AsyncMock(return_value=self.item1)
        self.receipts.save = AsyncMock(side_effect=lambda receipt: receipt)
        self.inspections = MagicMock()
        self.inspections.get_by_id = AsyncMock(return_value=self.inspection1)
        self.inspections.get_by_receipt_item_ids = AsyncMock(
            return_value=[self.inspection1, self.inspection2]
        )
        self.requests = [
            self._request(701, self.inspection1, StockStatus.PENDING_PUTAWAY, "7"),
            self._request(702, self.inspection1, StockStatus.DEFECTIVE, "2"),
            self._request(703, self.inspection2, StockStatus.QUARANTINED, "3"),
        ]
        self.dispatches = MagicMock()
        self.dispatches.get_by_inspection_ids = AsyncMock(return_value=self.requests)
        self.dispatches.get_for_update = AsyncMock(return_value=self.requests[0])
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = InboundCompletionService(
            self.session,  # type: ignore[arg-type]
            self.receipts,
            self.inspections,
            self.dispatches,
            self.audits,
        )

    async def test_multiple_items_and_quality_branches_complete_receipt(self) -> None:
        completed = await self.service.try_complete_receipt_in_transaction(
            201,
            trace_id="trace-complete",
        )

        self.assertTrue(completed)
        self.assertEqual(self.receipt.status, ReceiptStatus.COMPLETED)
        self.assertIsNotNone(self.receipt.completed_at)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "COMPLETE_INBOUND_RECEIPT")
        self.assertEqual(audit.metadata_["inspection_ids"], [501, 502])

    async def test_pending_request_prevents_completion(self) -> None:
        self.requests[1].status = DispatchRequestStatus.PENDING

        completed = await self.service.try_complete_receipt_in_transaction(
            201, trace_id="trace-pending"
        )

        self.assertFalse(completed)
        self.assertEqual(self.receipt.status, ReceiptStatus.INSPECTED)
        self.receipts.save.assert_not_awaited()

    async def test_published_but_incomplete_task_prevents_completion(self) -> None:
        self.requests[0].published_task.status = TaskStatus.EXECUTING

        completed = await self.service.try_complete_receipt_in_transaction(
            201, trace_id="trace-executing"
        )

        self.assertFalse(completed)
        self.assertEqual(self.receipt.status, ReceiptStatus.INSPECTED)

    async def test_fully_rejected_receipt_completes_without_requests(self) -> None:
        self.item1 = self._item(101, 201, 301, "10", "0", "0", "0", "10")
        self.receipts.get_items_for_update.return_value = [self.item1]
        inspection = self._inspection(501, 101, "10", "0", "0", "0", "10")
        self.inspections.get_by_receipt_item_ids.return_value = [inspection]
        self.dispatches.get_by_inspection_ids.return_value = []

        completed = await self.service.try_complete_receipt_in_transaction(
            201, trace_id="trace-rejected"
        )

        self.assertTrue(completed)
        self.assertEqual(self.receipt.status, ReceiptStatus.COMPLETED)

    async def test_missing_required_request_prevents_completion(self) -> None:
        self.dispatches.get_by_inspection_ids.return_value = self.requests[:-1]

        completed = await self.service.try_complete_receipt_in_transaction(
            201, trace_id="trace-missing"
        )

        self.assertFalse(completed)

    @staticmethod
    def _item(
        item_id: int,
        receipt_id: int,
        product_id: int,
        received: str,
        accepted: str,
        defective: str,
        quarantined: str,
        rejected: str,
    ) -> InboundReceiptItem:
        return InboundReceiptItem(
            id=item_id,
            inbound_receipt_id=receipt_id,
            product_id=product_id,
            expected_quantity=Decimal(received),
            received_quantity=Decimal(received),
            accepted_quantity=Decimal(accepted),
            defective_quantity=Decimal(defective),
            quarantined_quantity=Decimal(quarantined),
            rejected_quantity=Decimal(rejected),
        )

    @staticmethod
    def _inspection(
        inspection_id: int,
        item_id: int,
        received: str,
        accepted: str,
        defective: str,
        quarantined: str,
        rejected: str,
    ) -> ReceiptInspection:
        return ReceiptInspection(
            id=inspection_id,
            inbound_receipt_item_id=item_id,
            business_task_id=inspection_id + 1000,
            lot_no="LOT-1",
            received_quantity=Decimal(received),
            accepted_quantity=Decimal(accepted),
            defective_quantity=Decimal(defective),
            quarantined_quantity=Decimal(quarantined),
            rejected_quantity=Decimal(rejected),
            inspected_by_id=23,
        )

    @staticmethod
    def _request(
        request_id: int,
        inspection: ReceiptInspection,
        source_status: StockStatus,
        quantity: str,
    ) -> PutawayDispatchRequest:
        target_status = {
            StockStatus.PENDING_PUTAWAY: StockStatus.AVAILABLE,
            StockStatus.DEFECTIVE: StockStatus.DEFECTIVE,
            StockStatus.QUARANTINED: StockStatus.QUARANTINED,
        }[source_status]
        task = BusinessTask(
            id=request_id + 1000,
            task_no=f"PUTAWAY-{request_id}",
            task_type=TaskType.PUTAWAY,
            status=TaskStatus.COMPLETED,
            warehouse_id=1,
            assignee_id=23,
            source_type="PUTAWAY_DISPATCH",
            source_id=request_id,
        )
        task.items = [
            BusinessTaskItem(
                id=request_id + 2000,
                task_id=task.id,
                product_id=301,
                planned_quantity=Decimal(quantity),
                actual_quantity=Decimal(quantity),
            )
        ]
        request = PutawayDispatchRequest(
            id=request_id,
            inspection_id=inspection.id,
            source_bucket_id=request_id + 3000,
            warehouse_id=1,
            from_location_id=11,
            required_location_type=(
                WarehouseLocationType.STORAGE
                if source_status == StockStatus.PENDING_PUTAWAY
                else WarehouseLocationType.QUARANTINE
            ),
            target_stock_status=target_status,
            planned_quantity=Decimal(quantity),
            generation_key=f"PUTAWAY:{inspection.id}:{source_status.value}",
            status=DispatchRequestStatus.PUBLISHED,
            published_task_id=task.id,
        )
        request.published_task = task
        return request


if __name__ == "__main__":
    unittest.main()
