import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import ActorType, StockStatus
from app.core.exceptions import (
    InsufficientBucketStockError,
    InvalidInventoryBucketDataError,
    InventoryBucketNotFoundError,
)
from app.models.inventory_bucket import InventoryBucket
from app.services.inventory_bucket import InventoryBucketService


class FakeTransaction:
    def __init__(self, session: "FakeSession") -> None:
        self._session = session
        self.exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeTransaction":
        self._session.active = True
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        self.exception_type = exception_type
        self._session.active = False
        return False


class FakeSession:
    def __init__(self) -> None:
        self.active = False
        self.transactions: list[FakeTransaction] = []

    def begin(self) -> FakeTransaction:
        transaction = FakeTransaction(self)
        self.transactions.append(transaction)
        return transaction

    def in_transaction(self) -> bool:
        return self.active


def make_bucket(
    *,
    bucket_id: int,
    location: str,
    status: StockStatus,
    quantity: str,
) -> InventoryBucket:
    return InventoryBucket(
        id=bucket_id,
        product_id=1,
        warehouse_code="WH-A",
        location_code=location,
        lot_no="LOT-1",
        stock_status=status,
        quantity=Decimal(quantity),
    )


class InventoryBucketServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.buckets = MagicMock()
        self.buckets.get_for_update = AsyncMock()
        self.buckets.get_or_create_for_update = AsyncMock()
        self.buckets.save = AsyncMock(side_effect=lambda bucket: bucket)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = InventoryBucketService(
            self.session,  # type: ignore[arg-type]
            self.buckets,
            self.audits,
        )

    async def test_increase_requires_outer_transaction_and_writes_audit(self) -> None:
        bucket = make_bucket(
            bucket_id=11,
            location="RECEIVING",
            status=StockStatus.QUARANTINED,
            quantity="5.000",
        )
        self.buckets.get_or_create_for_update.return_value = bucket

        with self.assertRaisesRegex(RuntimeError, "active transaction"):
            await self.service.increase_in_transaction(
                1,
                "WH-A",
                3,
                location_code="RECEIVING",
                lot_no="LOT-1",
                stock_status=StockStatus.QUARANTINED,
            )

        self.session.active = True
        result = await self.service.increase_in_transaction(
            1,
            "WH-A",
            3,
            location_code="RECEIVING",
            lot_no="LOT-1",
            stock_status=StockStatus.QUARANTINED,
            actor_type=ActorType.EMPLOYEE,
            actor_id="23",
            trace_id="trace-1",
        )

        self.assertIs(result, bucket)
        self.assertEqual(bucket.quantity, Decimal("8.000"))
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "INCREASE_INVENTORY_BUCKET")
        self.assertEqual(audit.actor_id, "23")
        self.assertEqual(audit.before_data["source"]["quantity"], "5.000")
        self.assertEqual(audit.after_data["source"]["quantity"], "8.000")

    async def test_decrease_rejects_missing_and_insufficient_bucket(self) -> None:
        self.session.active = True
        self.buckets.get_for_update.return_value = None

        with self.assertRaises(InventoryBucketNotFoundError):
            await self.service.decrease_in_transaction(
                1,
                "WH-A",
                1,
                location_code="A-01",
                lot_no="LOT-1",
                stock_status=StockStatus.AVAILABLE,
            )

        bucket = make_bucket(
            bucket_id=12,
            location="A-01",
            status=StockStatus.AVAILABLE,
            quantity="2.000",
        )
        self.buckets.get_for_update.return_value = bucket
        with self.assertRaises(InsufficientBucketStockError):
            await self.service.decrease_in_transaction(
                1,
                "WH-A",
                3,
                location_code="A-01",
                lot_no="LOT-1",
                stock_status=StockStatus.AVAILABLE,
            )

        self.assertEqual(bucket.quantity, Decimal("2.000"))
        self.buckets.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_move_transfers_quantity_without_changing_total(self) -> None:
        source = make_bucket(
            bucket_id=13,
            location="A-01",
            status=StockStatus.AVAILABLE,
            quantity="10.000",
        )
        destination = make_bucket(
            bucket_id=14,
            location="PICK-01",
            status=StockStatus.RESERVED,
            quantity="2.000",
        )

        async def get_destination(
            product_id: int,
            warehouse_code: str,
            location_code: str,
            lot_no: str,
            stock_status: StockStatus,
        ) -> InventoryBucket:
            return destination

        self.buckets.get_for_update.return_value = source
        self.buckets.get_or_create_for_update.side_effect = get_destination

        result_source, result_destination = await self.service.move(
            1,
            "WH-A",
            4,
            from_location_code="A-01",
            from_lot_no="LOT-1",
            from_status=StockStatus.AVAILABLE,
            to_location_code="PICK-01",
            to_lot_no="LOT-1",
            to_status=StockStatus.RESERVED,
        )

        self.assertIs(result_source, source)
        self.assertIs(result_destination, destination)
        self.assertEqual(source.quantity, Decimal("6.000"))
        self.assertEqual(destination.quantity, Decimal("6.000"))
        self.assertEqual(source.quantity + destination.quantity, Decimal("12.000"))
        self.assertEqual(self.buckets.save.await_count, 2)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "MOVE_INVENTORY_BUCKET")
        self.assertEqual(audit.metadata_["quantity"], "4")
        self.assertIsNone(self.session.transactions[0].exception_type)

    async def test_move_rejects_missing_source_bucket(self) -> None:
        self.buckets.get_for_update.return_value = None

        with self.assertRaises(InventoryBucketNotFoundError):
            await self.service.move(
                1,
                "WH-A",
                1,
                from_location_code="A-01",
                from_lot_no="LOT-1",
                from_status=StockStatus.AVAILABLE,
                to_location_code="PICK-01",
                to_lot_no="LOT-1",
                to_status=StockStatus.RESERVED,
            )

        self.buckets.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()

    async def test_move_rejects_same_bucket_before_transaction(self) -> None:
        with self.assertRaises(InvalidInventoryBucketDataError):
            await self.service.move(
                1,
                "WH-A",
                1,
                from_location_code="A-01",
                from_lot_no="LOT-1",
                from_status=StockStatus.AVAILABLE,
                to_location_code="A-01",
                to_lot_no="LOT-1",
                to_status=StockStatus.AVAILABLE,
            )

        self.assertEqual(self.session.transactions, [])
        self.buckets.get_or_create_for_update.assert_not_awaited()

    async def test_move_failure_aborts_transaction(self) -> None:
        source = make_bucket(
            bucket_id=15,
            location="A-01",
            status=StockStatus.AVAILABLE,
            quantity="1.000",
        )
        destination = make_bucket(
            bucket_id=16,
            location="PICK-01",
            status=StockStatus.RESERVED,
            quantity="0.000",
        )
        self.buckets.get_for_update.return_value = source
        self.buckets.get_or_create_for_update.return_value = destination

        with self.assertRaises(InsufficientBucketStockError):
            await self.service.move(
                1,
                "WH-A",
                2,
                from_location_code="A-01",
                from_lot_no="LOT-1",
                from_status=StockStatus.AVAILABLE,
                to_location_code="PICK-01",
                to_lot_no="LOT-1",
                to_status=StockStatus.RESERVED,
            )

        self.assertIs(
            self.session.transactions[0].exception_type,
            InsufficientBucketStockError,
        )
        self.buckets.save.assert_not_awaited()
        self.audits.append.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
