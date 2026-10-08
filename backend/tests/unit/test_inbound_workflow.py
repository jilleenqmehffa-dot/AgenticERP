import unittest
from dataclasses import replace
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import (
    DispatchRequestStatus,
    StockStatus,
    TaskStatus,
    TaskType,
    WarehouseLocationType,
)
from app.models.business_task import BusinessTask
from app.models.putaway_dispatch_request import PutawayDispatchRequest
from app.domain.inbound.contracts import ReceivingDisposition, ReceivingResult
from app.workflows.inbound import InboundWorkflow


class FakeSession:
    def in_transaction(self) -> bool:
        return True


class InboundWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.dispatches = MagicMock()
        self.dispatches.get_by_generation_key = AsyncMock(return_value=None)

        async def save_request(
            request: PutawayDispatchRequest,
        ) -> PutawayDispatchRequest:
            request.id = request.id or 700 + self.dispatches.save.await_count
            return request

        self.dispatches.save = AsyncMock(side_effect=save_request)
        self.completion = MagicMock()
        self.completion.try_complete_receipt_in_transaction = AsyncMock(
            return_value=False
        )
        self.completion.try_complete_for_dispatch_in_transaction = AsyncMock(
            return_value=False
        )
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.workflow = InboundWorkflow(
            self.session,  # type: ignore[arg-type]
            dispatch_repository=self.dispatches,
            completion_service=self.completion,
            audit_repository=self.audits,
        )
        self.task = BusinessTask(
            id=1001,
            task_no="RECEIVE-1001",
            task_type=TaskType.RECEIVE,
            status=TaskStatus.COMPLETED,
            warehouse_id=1,
            assignee_id=23,
        )
        self.result = ReceivingResult(
            receipt_id=201,
            receipt_item_id=101,
            inspection_id=501,
            warehouse_id=1,
            receiving_location_id=21,
            product_id=301,
            lot_no="LOT-1",
            rejected_quantity=Decimal("1.000"),
            dispositions=(
                ReceivingDisposition(
                    401, StockStatus.PENDING_PUTAWAY, Decimal("92.000")
                ),
                ReceivingDisposition(402, StockStatus.DEFECTIVE, Decimal("3.000")),
                ReceivingDisposition(
                    403, StockStatus.QUARANTINED, Decimal("4.000")
                ),
            ),
        )

    async def test_receive_creates_pending_requests_for_nonzero_dispositions(
        self,
    ) -> None:
        await self.workflow.after_task_completed_in_transaction(
            self.task,
            self.result,
            trace_id="trace-receive",
        )

        self.assertEqual(self.dispatches.save.await_count, 3)
        requests = [call.args[0] for call in self.dispatches.save.await_args_list]
        self.assertEqual(
            {request.generation_key for request in requests},
            {
                "PUTAWAY:501:PENDING_PUTAWAY",
                "PUTAWAY:501:DEFECTIVE",
                "PUTAWAY:501:QUARANTINED",
            },
        )
        routes = {
            request.generation_key: (
                request.required_location_type,
                request.target_stock_status,
            )
            for request in requests
        }
        self.assertEqual(
            routes["PUTAWAY:501:PENDING_PUTAWAY"],
            (WarehouseLocationType.STORAGE, StockStatus.AVAILABLE),
        )
        self.assertEqual(
            routes["PUTAWAY:501:DEFECTIVE"],
            (WarehouseLocationType.QUARANTINE, StockStatus.DEFECTIVE),
        )
        self.assertTrue(
            all(request.status == DispatchRequestStatus.PENDING for request in requests)
        )
        self.completion.try_complete_receipt_in_transaction.assert_awaited_once_with(
            201,
            trace_id="trace-receive",
        )

    async def test_generation_key_is_idempotent(self) -> None:
        existing = PutawayDispatchRequest(
            id=701,
            inspection_id=501,
            source_bucket_id=401,
            warehouse_id=1,
            from_location_id=21,
            required_location_type=WarehouseLocationType.STORAGE,
            target_stock_status=StockStatus.AVAILABLE,
            planned_quantity=Decimal("92.000"),
            generation_key="PUTAWAY:501:PENDING_PUTAWAY",
            status=DispatchRequestStatus.PENDING,
        )
        single = replace(
            self.result,
            dispositions=(self.result.dispositions[0],),
        )
        self.dispatches.get_by_generation_key.return_value = existing

        await self.workflow.after_task_completed_in_transaction(
            self.task,
            single,
            trace_id="trace-retry",
        )

        self.dispatches.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_all_rejected_creates_no_request_and_checks_completion(self) -> None:
        rejected = replace(self.result, dispositions=())

        await self.workflow.after_task_completed_in_transaction(
            self.task,
            rejected,
            trace_id="trace-rejected",
        )

        self.dispatches.save.assert_not_awaited()
        self.completion.try_complete_receipt_in_transaction.assert_awaited_once()

    async def test_dispatch_putaway_completion_delegates_close_check(self) -> None:
        task = BusinessTask(
            id=900,
            task_no="PUTAWAY-77",
            task_type=TaskType.PUTAWAY,
            status=TaskStatus.COMPLETED,
            warehouse_id=1,
            assignee_id=24,
            source_type="PUTAWAY_DISPATCH",
            source_id=77,
        )

        await self.workflow.after_task_completed_in_transaction(
            task,
            None,
            trace_id="trace-putaway",
        )

        self.completion.try_complete_for_dispatch_in_transaction.assert_awaited_once_with(
            77,
            trace_id="trace-putaway",
        )


if __name__ == "__main__":
    unittest.main()
