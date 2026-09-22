import unittest

from app.core.enums import (
    OrderItemStatus,
    OutboundStatus,
    PayableStatus,
    PurchaseOrderStatus,
    ReceiptStatus,
    ReceivableStatus,
    ReservationStatus,
    ReturnStatus,
    SalesOrderStatus,
    StockStatus,
    TaskStatus,
    TransferStatus,
)
from app.models.inbound_receipt import InboundReceipt
from app.models.inbound_receipt_item import InboundReceiptItem
from app.models.inventory_bucket import InventoryBucket
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.purchase_order import PurchaseOrder
from app.models.purchase_order_item import PurchaseOrderItem
from app.models.return_order import ReturnOrder
from app.models.return_order_item import ReturnOrderItem
from app.models.sales_order_item import SalesOrderItem
from app.models.stock_reservation import StockReservation
from app.models.stock_transfer import StockTransfer
from app.models.stock_transfer_item import StockTransferItem


class WarehouseModelTests(unittest.TestCase):
    def test_no_current_status_contains_partially(self) -> None:
        status_enums = (
            SalesOrderStatus,
            ReceivableStatus,
            PayableStatus,
            TaskStatus,
            OrderItemStatus,
            OutboundStatus,
            ReservationStatus,
            PurchaseOrderStatus,
            ReceiptStatus,
            ReturnStatus,
            TransferStatus,
            StockStatus,
        )

        for status_enum in status_enums:
            with self.subTest(status_enum=status_enum.__name__):
                self.assertFalse(
                    any("PARTIALLY" in member.value for member in status_enum)
                )

    def test_requested_warehouse_states_are_present(self) -> None:
        self.assertIn(OutboundStatus.PENDING_OUTBOUND, OutboundStatus)
        self.assertIn(OutboundStatus.RESERVED, OutboundStatus)
        self.assertIn(OutboundStatus.PICKING, OutboundStatus)
        self.assertIn(OutboundStatus.READY_TO_SHIP, OutboundStatus)
        self.assertIn(PurchaseOrderStatus.ORDERED, PurchaseOrderStatus)
        self.assertIn(PurchaseOrderStatus.IN_TRANSIT, PurchaseOrderStatus)
        self.assertIn(ReceiptStatus.PENDING_RECEIPT, ReceiptStatus)
        self.assertIn(ReceiptStatus.PENDING_INSPECTION, ReceiptStatus)
        self.assertIn(ReturnStatus.IN_TRANSIT, ReturnStatus)
        self.assertIn(ReturnStatus.PENDING_OUTBOUND, ReturnStatus)
        self.assertIn(TransferStatus.IN_TRANSIT, TransferStatus)
        self.assertIn(StockStatus.FROZEN, StockStatus)
        self.assertIn(StockStatus.QUARANTINED, StockStatus)
        self.assertIn(StockStatus.DEFECTIVE, StockStatus)

    def test_all_warehouse_models_are_registered(self) -> None:
        expected_tables = {
            OutboundOrder: "outbound_orders",
            OutboundOrderItem: "outbound_order_items",
            StockReservation: "stock_reservations",
            PurchaseOrder: "purchase_orders",
            PurchaseOrderItem: "purchase_order_items",
            InboundReceipt: "inbound_receipts",
            InboundReceiptItem: "inbound_receipt_items",
            ReturnOrder: "return_orders",
            ReturnOrderItem: "return_order_items",
            StockTransfer: "stock_transfers",
            StockTransferItem: "stock_transfer_items",
            InventoryBucket: "inventory_buckets",
        }

        for model, table_name in expected_tables.items():
            with self.subTest(model=model.__name__):
                self.assertEqual(model.__tablename__, table_name)

    def test_quantity_progress_is_stored_on_lines(self) -> None:
        expected_columns = {
            SalesOrderItem: {
                "quantity",
                "reserved_quantity",
                "picked_quantity",
                "shipped_quantity",
            },
            OutboundOrderItem: {
                "requested_quantity",
                "reserved_quantity",
                "picked_quantity",
                "shipped_quantity",
            },
            PurchaseOrderItem: {
                "ordered_quantity",
                "received_quantity",
                "accepted_quantity",
                "rejected_quantity",
            },
            InboundReceiptItem: {
                "expected_quantity",
                "received_quantity",
                "accepted_quantity",
                "defective_quantity",
                "quarantined_quantity",
                "rejected_quantity",
            },
            StockTransferItem: {
                "planned_quantity",
                "shipped_quantity",
                "received_quantity",
            },
        }

        for model, column_names in expected_columns.items():
            with self.subTest(model=model.__name__):
                self.assertTrue(column_names <= set(model.__table__.columns.keys()))


if __name__ == "__main__":
    unittest.main()
