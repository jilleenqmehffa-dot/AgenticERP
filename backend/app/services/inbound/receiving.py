from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    ReceiptStatus,
    StockStatus,
    WarehouseLocationType,
)
from app.core.exceptions import (
    InboundReceiptItemNotFoundError,
    InvalidReceivingDataError,
    InvalidReceivingStateError,
)
from app.core.validation import (
    actor_id as validate_actor_id,
    actor_type as validate_actor_type,
    decimal_quantity,
    positive_int,
    trace_id as validate_trace_id,
)
from app.domain.inbound.contracts import ReceivingDisposition, ReceivingResult
from app.domain.inbound.policies import is_receipt_item_fully_classified
from app.models.audit_log import AuditLog
from app.models.inbound_receipt_item import InboundReceiptItem
from app.models.receipt_inspection import ReceiptInspection
from app.repositories.audit_log import AuditLogRepository
from app.repositories.inbound_receipt import InboundReceiptRepository
from app.repositories.receipt_inspection import ReceiptInspectionRepository
from app.repositories.warehouse_location import WarehouseLocationRepository
from app.services.inventory.bucket import InventoryBucketService

class ReceivingService:
    def __init__(
        self,
        session: AsyncSession,
        receipt_repository: InboundReceiptRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
        bucket_service: InventoryBucketService | None = None,
        inspection_repository: ReceiptInspectionRepository | None = None,
        location_repository: WarehouseLocationRepository | None = None,
    ) -> None:
        self._session = session
        self._receipts = receipt_repository or InboundReceiptRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)
        self._buckets = bucket_service or InventoryBucketService(session)
        self._inspections = inspection_repository or ReceiptInspectionRepository(session)
        self._locations = location_repository or WarehouseLocationRepository(session)

    async def receive_and_inspect(
        self,
        inbound_receipt_item_id: int,
        *,
        received_quantity: Decimal | int,
        accepted_quantity: Decimal | int,
        defective_quantity: Decimal | int,
        quarantined_quantity: Decimal | int = 0,
        rejected_quantity: Decimal | int = 0,
        expected_product_id: int,
        business_task_id: int,
        warehouse_id: int,
        warehouse_code: str,
        receiving_location_id: int,
        assignee_id: int,
        lot_no: str = "",
        inspection_note: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> ReceivingResult:
        values = self._validate(
            inbound_receipt_item_id=inbound_receipt_item_id,
            received_quantity=received_quantity,
            accepted_quantity=accepted_quantity,
            defective_quantity=defective_quantity,
            quarantined_quantity=quarantined_quantity,
            rejected_quantity=rejected_quantity,
            expected_product_id=expected_product_id,
            business_task_id=business_task_id,
            warehouse_id=warehouse_id,
            warehouse_code=warehouse_code,
            receiving_location_id=receiving_location_id,
            assignee_id=assignee_id,
            lot_no=lot_no,
            inspection_note=inspection_note,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        async with self._session.begin():
            return await self._receive_and_inspect_in_transaction(**values)

    async def receive_and_inspect_in_transaction(
        self,
        inbound_receipt_item_id: int,
        *,
        received_quantity: Decimal | int,
        accepted_quantity: Decimal | int,
        defective_quantity: Decimal | int,
        quarantined_quantity: Decimal | int = 0,
        rejected_quantity: Decimal | int = 0,
        expected_product_id: int,
        business_task_id: int,
        warehouse_id: int,
        warehouse_code: str,
        receiving_location_id: int,
        assignee_id: int,
        lot_no: str = "",
        inspection_note: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> ReceivingResult:
        if not self._session.in_transaction():
            raise RuntimeError(
                "receive_and_inspect_in_transaction requires an active transaction"
            )
        values = self._validate(
            inbound_receipt_item_id=inbound_receipt_item_id,
            received_quantity=received_quantity,
            accepted_quantity=accepted_quantity,
            defective_quantity=defective_quantity,
            quarantined_quantity=quarantined_quantity,
            rejected_quantity=rejected_quantity,
            expected_product_id=expected_product_id,
            business_task_id=business_task_id,
            warehouse_id=warehouse_id,
            warehouse_code=warehouse_code,
            receiving_location_id=receiving_location_id,
            assignee_id=assignee_id,
            lot_no=lot_no,
            inspection_note=inspection_note,
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        return await self._receive_and_inspect_in_transaction(**values)

    async def _receive_and_inspect_in_transaction(
        self,
        *,
        inbound_receipt_item_id: int,
        received_quantity: Decimal,
        accepted_quantity: Decimal,
        defective_quantity: Decimal,
        quarantined_quantity: Decimal,
        rejected_quantity: Decimal,
        expected_product_id: int,
        business_task_id: int,
        warehouse_id: int,
        warehouse_code: str,
        receiving_location_id: int,
        assignee_id: int,
        lot_no: str,
        inspection_note: str | None,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> ReceivingResult:
        item_reference = await self._receipts.get_item(inbound_receipt_item_id)
        if item_reference is None:
            raise InboundReceiptItemNotFoundError(inbound_receipt_item_id)
        receipt = await self._receipts.get_for_update(
            item_reference.inbound_receipt_id
        )
        if receipt is None:
            raise InvalidReceivingDataError("inbound receipt does not exist")
        if receipt.warehouse_code != warehouse_code:
            raise InvalidReceivingDataError(
                "receiving task warehouse does not match inbound receipt"
            )
        if receipt.status not in {
            ReceiptStatus.PENDING_RECEIPT,
            ReceiptStatus.RECEIVING,
        }:
            raise InvalidReceivingStateError(receipt.id)

        items = await self._receipts.get_items_for_update(receipt.id)
        item = self._find_item(items, inbound_receipt_item_id)
        if item.product_id != expected_product_id:
            raise InvalidReceivingDataError(
                "receiving task product does not match inbound receipt item"
            )
        if item.received_quantity + received_quantity > item.expected_quantity:
            raise InvalidReceivingDataError(
                "received quantity exceeds inbound receipt item remainder"
            )

        receiving_location = await self._locations.get_for_update(
            receiving_location_id
        )
        if (
            receiving_location is None
            or receiving_location.warehouse_id != warehouse_id
            or receiving_location.location_type != WarehouseLocationType.RECEIVING
            or not receiving_location.is_active
        ):
            raise InvalidReceivingDataError(
                "receiving location must be an active RECEIVING location in the task warehouse"
            )

        before = self._snapshot(item)
        item.received_quantity += received_quantity
        item.accepted_quantity += accepted_quantity
        item.defective_quantity += defective_quantity
        item.quarantined_quantity += quarantined_quantity
        item.rejected_quantity += rejected_quantity
        await self._receipts.save_item(item)

        inspection = await self._inspections.save(
            ReceiptInspection(
                inbound_receipt_item_id=item.id,
                business_task_id=business_task_id,
                lot_no=lot_no,
                received_quantity=received_quantity,
                accepted_quantity=accepted_quantity,
                defective_quantity=defective_quantity,
                quarantined_quantity=quarantined_quantity,
                rejected_quantity=rejected_quantity,
                inspection_note=inspection_note,
                inspected_by_id=assignee_id,
            )
        )
        dispositions = await self._record_disposition_buckets(
            product_id=item.product_id,
            warehouse_code=warehouse_code,
            receiving_location_code=receiving_location.code,
            lot_no=lot_no,
            quantities=(
                (accepted_quantity, StockStatus.PENDING_PUTAWAY),
                (defective_quantity, StockStatus.DEFECTIVE),
                (quarantined_quantity, StockStatus.QUARANTINED),
            ),
            actor_type=actor_type,
            actor_id=actor_id,
            trace_id=trace_id,
        )
        now = datetime.now(timezone.utc)
        before_status = receipt.status
        receipt.status = ReceiptStatus.RECEIVING
        if items and all(self._item_is_complete(receipt_item) for receipt_item in items):
            receipt.status = ReceiptStatus.INSPECTED
            receipt.received_at = now
            receipt.inspected_at = now
        await self._receipts.save(receipt)

        if inspection.id is None:
            raise RuntimeError("saved receipt inspection has no id")
        await self._audits.append(
            AuditLog(
                actor_type=actor_type,
                actor_id=actor_id,
                action="RECEIVE_AND_INSPECT_GOODS",
                entity_type="INBOUND_RECEIPT_ITEM",
                entity_id=str(item.id),
                before_data=before,
                after_data=self._snapshot(item),
                trace_id=trace_id,
                metadata_={
                    "inbound_receipt_id": receipt.id,
                    "receipt_status_before": before_status.value,
                    "receipt_status_after": receipt.status.value,
                    "inspection_id": inspection.id,
                    "disposition_bucket_ids": [
                        entry.bucket_id for entry in dispositions
                    ],
                },
            )
        )
        return ReceivingResult(
            receipt_id=receipt.id,
            receipt_item_id=item.id,
            inspection_id=inspection.id,
            warehouse_id=warehouse_id,
            receiving_location_id=receiving_location_id,
            product_id=item.product_id,
            lot_no=lot_no,
            rejected_quantity=rejected_quantity,
            dispositions=dispositions,
        )

    async def _record_disposition_buckets(
        self,
        *,
        product_id: int,
        warehouse_code: str,
        receiving_location_code: str,
        lot_no: str,
        quantities: tuple[tuple[Decimal, StockStatus], ...],
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> tuple[ReceivingDisposition, ...]:
        dispositions: list[ReceivingDisposition] = []
        for quantity, stock_status in quantities:
            if quantity == 0:
                continue
            bucket = await self._buckets.increase_in_transaction(
                product_id,
                warehouse_code,
                quantity,
                location_code=receiving_location_code,
                lot_no=lot_no,
                stock_status=stock_status,
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
            )
            if bucket.id is None:
                raise RuntimeError("saved inventory bucket has no id")
            dispositions.append(
                ReceivingDisposition(
                    bucket_id=bucket.id,
                    stock_status=stock_status,
                    quantity=quantity,
                )
            )
        return tuple(dispositions)

    @staticmethod
    def _find_item(
        items: list[InboundReceiptItem],
        item_id: int,
    ) -> InboundReceiptItem:
        for item in items:
            if item.id == item_id:
                return item
        raise InboundReceiptItemNotFoundError(item_id)

    @staticmethod
    def _item_is_complete(item: InboundReceiptItem) -> bool:
        return is_receipt_item_fully_classified(item)

    @staticmethod
    def _snapshot(item: InboundReceiptItem) -> dict[str, str]:
        return {
            "received_quantity": str(item.received_quantity),
            "accepted_quantity": str(item.accepted_quantity),
            "defective_quantity": str(item.defective_quantity),
            "quarantined_quantity": str(item.quarantined_quantity),
            "rejected_quantity": str(item.rejected_quantity),
        }

    @classmethod
    def _validate(cls, **values: object) -> dict[str, object]:
        received = cls._quantity(values["received_quantity"], "received_quantity")
        accepted = cls._quantity(
            values["accepted_quantity"], "accepted_quantity", allow_zero=True
        )
        defective = cls._quantity(
            values["defective_quantity"], "defective_quantity", allow_zero=True
        )
        quarantined = cls._quantity(
            values["quarantined_quantity"],
            "quarantined_quantity",
            allow_zero=True,
        )
        rejected = cls._quantity(
            values["rejected_quantity"], "rejected_quantity", allow_zero=True
        )
        if accepted + defective + quarantined + rejected != received:
            raise InvalidReceivingDataError(
                "quality quantities must equal received_quantity"
            )
        actor_type = cls._actor_type(values["actor_type"])
        return {
            "inbound_receipt_item_id": cls._positive_id(
                values["inbound_receipt_item_id"], "inbound_receipt_item_id"
            ),
            "received_quantity": received,
            "accepted_quantity": accepted,
            "defective_quantity": defective,
            "quarantined_quantity": quarantined,
            "rejected_quantity": rejected,
            "expected_product_id": cls._positive_id(
                values["expected_product_id"], "expected_product_id"
            ),
            "business_task_id": cls._positive_id(
                values["business_task_id"], "business_task_id"
            ),
            "warehouse_id": cls._positive_id(values["warehouse_id"], "warehouse_id"),
            "warehouse_code": cls._required_code(
                values["warehouse_code"], "warehouse_code", 64
            ),
            "receiving_location_id": cls._positive_id(
                values["receiving_location_id"], "receiving_location_id"
            ),
            "assignee_id": cls._positive_id(values["assignee_id"], "assignee_id"),
            "lot_no": cls._optional_text(values["lot_no"], "lot_no", 100) or "",
            "inspection_note": cls._optional_text(
                values["inspection_note"], "inspection_note", 2000
            ),
            "actor_type": actor_type,
            "actor_id": cls._actor_id(actor_type, values["actor_id"]),
            "trace_id": cls._trace_id(values["trace_id"]),
        }

    @staticmethod
    def _required_code(value: object, field_name: str, max_length: int) -> str:
        if not isinstance(value, str) or not value.strip():
            raise InvalidReceivingDataError(f"{field_name} is required")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise InvalidReceivingDataError(f"{field_name} is too long")
        return normalized

    @staticmethod
    def _optional_text(
        value: object, field_name: str, max_length: int
    ) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            raise InvalidReceivingDataError(f"{field_name} must be a string")
        normalized = value.strip()
        if len(normalized) > max_length:
            raise InvalidReceivingDataError(f"{field_name} is too long")
        return normalized or None

    @staticmethod
    def _positive_id(value: object, field_name: str) -> int:
        return positive_int(value, field_name, error=InvalidReceivingDataError)

    @staticmethod
    def _quantity(
        value: object,
        field_name: str,
        *,
        allow_zero: bool = False,
    ) -> Decimal:
        return decimal_quantity(
            value,
            field_name,
            allow_zero=allow_zero,
            error=InvalidReceivingDataError,
        )

    @staticmethod
    def _actor_type(value: object) -> ActorType:
        return validate_actor_type(
            value,
            coerce=True,
            error=InvalidReceivingDataError,
        )

    @staticmethod
    def _actor_id(actor_type: ActorType, value: object) -> str:
        return validate_actor_id(
            actor_type,
            value,
            error=InvalidReceivingDataError,
        )

    @staticmethod
    def _trace_id(value: object) -> str:
        return validate_trace_id(value, error=InvalidReceivingDataError)
