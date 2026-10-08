from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from app.core.enums import StockStatus, WarehouseLocationType


@dataclass(frozen=True, slots=True)
class PutawayRoute:
    required_location_type: WarehouseLocationType
    target_stock_status: StockStatus


PUTAWAY_ROUTES = {
    StockStatus.PENDING_PUTAWAY: PutawayRoute(
        WarehouseLocationType.STORAGE,
        StockStatus.AVAILABLE,
    ),
    StockStatus.DEFECTIVE: PutawayRoute(
        WarehouseLocationType.QUARANTINE,
        StockStatus.DEFECTIVE,
    ),
    StockStatus.QUARANTINED: PutawayRoute(
        WarehouseLocationType.QUARANTINE,
        StockStatus.QUARANTINED,
    ),
}


def get_putaway_route(source_status: StockStatus) -> PutawayRoute | None:
    return PUTAWAY_ROUTES.get(source_status)


def putaway_generation_key(
    inspection_id: int,
    source_status: StockStatus,
) -> str:
    return f"PUTAWAY:{inspection_id}:{source_status.value}"


class ClassifiedReceiptItem(Protocol):
    expected_quantity: Decimal
    received_quantity: Decimal
    accepted_quantity: Decimal
    defective_quantity: Decimal
    quarantined_quantity: Decimal
    rejected_quantity: Decimal


def is_receipt_item_fully_classified(item: ClassifiedReceiptItem) -> bool:
    classified = (
        item.accepted_quantity
        + item.defective_quantity
        + item.quarantined_quantity
        + item.rejected_quantity
    )
    return (
        item.received_quantity == item.expected_quantity
        and classified == item.received_quantity
    )
