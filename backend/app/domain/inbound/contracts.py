from dataclasses import dataclass
from decimal import Decimal

from app.core.enums import StockStatus


@dataclass(frozen=True, slots=True)
class ReceivingDisposition:
    bucket_id: int
    stock_status: StockStatus
    quantity: Decimal


@dataclass(frozen=True, slots=True)
class ReceivingResult:
    receipt_id: int
    receipt_item_id: int
    inspection_id: int
    warehouse_id: int
    receiving_location_id: int
    product_id: int
    lot_no: str
    rejected_quantity: Decimal
    dispositions: tuple[ReceivingDisposition, ...]
