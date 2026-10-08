from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    DispatchRequestStatus,
    ReceiptStatus,
    StockStatus,
    TaskStatus,
    TaskType,
)
from app.core.exceptions import InvalidTaskDataError
from app.domain.inbound.policies import (
    is_receipt_item_fully_classified,
    putaway_generation_key,
)
from app.models.audit_log import AuditLog
from app.models.inbound_receipt_item import InboundReceiptItem
from app.models.receipt_inspection import ReceiptInspection
from app.repositories.audit_log import AuditLogRepository
from app.repositories.inbound_receipt import InboundReceiptRepository
from app.repositories.putaway_dispatch import PutawayDispatchRepository
from app.repositories.receipt_inspection import ReceiptInspectionRepository


class InboundCompletionService:
    def __init__(
        self,
        session: AsyncSession,
        receipt_repository: InboundReceiptRepository | None = None,
        inspection_repository: ReceiptInspectionRepository | None = None,
        dispatch_repository: PutawayDispatchRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._receipts = receipt_repository or InboundReceiptRepository(session)
        self._inspections = inspection_repository or ReceiptInspectionRepository(
            session
        )
        self._dispatches = dispatch_repository or PutawayDispatchRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def try_complete_for_dispatch_in_transaction(
        self,
        request_id: int,
        *,
        trace_id: str,
    ) -> bool:
        self._require_transaction()
        request = await self._dispatches.get_for_update(request_id)
        if request is None:
            raise InvalidTaskDataError(
                f"putaway dispatch request does not exist: {request_id}"
            )
        inspection = await self._inspections.get_by_id(request.inspection_id)
        if inspection is None:
            raise InvalidTaskDataError(
                f"receipt inspection does not exist: {request.inspection_id}"
            )
        receipt_item = await self._receipts.get_item(
            inspection.inbound_receipt_item_id
        )
        if receipt_item is None:
            raise InvalidTaskDataError(
                f"inbound receipt item does not exist: "
                f"{inspection.inbound_receipt_item_id}"
            )
        return await self.try_complete_receipt_in_transaction(
            receipt_item.inbound_receipt_id,
            trace_id=trace_id,
        )

    async def try_complete_receipt_in_transaction(
        self,
        receipt_id: int,
        *,
        trace_id: str,
    ) -> bool:
        self._require_transaction()
        receipt = await self._receipts.get_for_update(receipt_id)
        if receipt is None:
            raise InvalidTaskDataError(
                f"inbound receipt does not exist: {receipt_id}"
            )
        if receipt.status == ReceiptStatus.COMPLETED:
            return True
        if receipt.status != ReceiptStatus.INSPECTED:
            return False

        items = await self._receipts.get_items_for_update(receipt.id)
        if not items or not all(self._item_is_complete(item) for item in items):
            return False
        item_ids = {item.id for item in items}
        inspections = await self._inspections.get_by_receipt_item_ids(item_ids)
        if not self._inspection_totals_match(items, inspections):
            return False

        expected_keys = self._expected_generation_keys(inspections)
        requests = await self._dispatches.get_by_inspection_ids(
            {inspection.id for inspection in inspections}
        )
        requests_by_key = {request.generation_key: request for request in requests}
        if set(requests_by_key) != expected_keys:
            return False
        for generation_key in expected_keys:
            request = requests_by_key[generation_key]
            task = request.published_task
            if (
                request.status != DispatchRequestStatus.PUBLISHED
                or request.published_task_id is None
                or task is None
                or task.id != request.published_task_id
                or task.task_type != TaskType.PUTAWAY
                or task.status != TaskStatus.COMPLETED
                or task.source_type != "PUTAWAY_DISPATCH"
                or task.source_id != request.id
                or len(task.items) != 1
                or task.items[0].actual_quantity
                != task.items[0].planned_quantity
                or task.items[0].planned_quantity != request.planned_quantity
            ):
                return False

        completed_at = datetime.now(timezone.utc)
        receipt.status = ReceiptStatus.COMPLETED
        receipt.completed_at = completed_at
        await self._receipts.save(receipt)
        await self._audits.append(
            AuditLog(
                actor_type=ActorType.SYSTEM,
                actor_id="INBOUND_WORKFLOW",
                action="COMPLETE_INBOUND_RECEIPT",
                entity_type="INBOUND_RECEIPT",
                entity_id=str(receipt.id),
                before_data={"status": ReceiptStatus.INSPECTED.value},
                after_data={
                    "status": ReceiptStatus.COMPLETED.value,
                    "completed_at": completed_at.isoformat(),
                },
                trace_id=trace_id,
                metadata_={
                    "inspection_ids": [inspection.id for inspection in inspections],
                    "dispatch_request_ids": [
                        requests_by_key[key].id for key in sorted(expected_keys)
                    ],
                },
            )
        )
        return True

    def _require_transaction(self) -> None:
        if not self._session.in_transaction():
            raise RuntimeError(
                "inbound completion requires an active transaction"
            )

    @staticmethod
    def _item_is_complete(item: InboundReceiptItem) -> bool:
        return is_receipt_item_fully_classified(item)

    @staticmethod
    def _inspection_totals_match(
        items: list[InboundReceiptItem],
        inspections: list[ReceiptInspection],
    ) -> bool:
        totals: dict[int, list[Decimal]] = defaultdict(
            lambda: [Decimal("0"), Decimal("0"), Decimal("0"), Decimal("0")]
        )
        for inspection in inspections:
            total = totals[inspection.inbound_receipt_item_id]
            total[0] += inspection.accepted_quantity
            total[1] += inspection.defective_quantity
            total[2] += inspection.quarantined_quantity
            total[3] += inspection.rejected_quantity
        return all(
            totals[item.id]
            == [
                item.accepted_quantity,
                item.defective_quantity,
                item.quarantined_quantity,
                item.rejected_quantity,
            ]
            for item in items
        )

    @staticmethod
    def _expected_generation_keys(
        inspections: list[ReceiptInspection],
    ) -> set[str]:
        expected: set[str] = set()
        for inspection in inspections:
            quantities = (
                (StockStatus.PENDING_PUTAWAY, inspection.accepted_quantity),
                (StockStatus.DEFECTIVE, inspection.defective_quantity),
                (StockStatus.QUARANTINED, inspection.quarantined_quantity),
            )
            for stock_status, quantity in quantities:
                if quantity > 0:
                    expected.add(putaway_generation_key(inspection.id, stock_status))
        return expected
