import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.capabilities.packing import PackingCapability
from app.core.enums import ActorType, TaskType
from app.core.exceptions import (
    InvalidTaskDataError,
)
from app.models.business_task import BusinessTask
from app.models.business_task_item import BusinessTaskItem
from app.models.employee import Employee
from app.models.outbound_order_item import OutboundOrderItem
from app.services.packing import PackingService


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


class PackingServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.item = OutboundOrderItem(
            id=101,
            outbound_order_id=201,
            product_id=301,
            requested_quantity=Decimal("10.000"),
            reserved_quantity=Decimal("10.000"),
            picked_quantity=Decimal("10.000"),
            packed_at=None,
            shipped_quantity=Decimal("0.000"),
        )
        self.outbound = MagicMock()
        self.outbound.get_item_for_update = AsyncMock(return_value=self.item)
        self.outbound.save_item = AsyncMock(side_effect=lambda item: item)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)
        self.service = PackingService(
            self.session,  # type: ignore[arg-type]
            self.outbound,
            self.audits,
        )

    async def test_pack_marks_goods_as_packed_and_writes_audit(self) -> None:
        result = await self.service.mark_packed(
            101,
            actor_type=ActorType.EMPLOYEE,
            actor_id="23",
            trace_id="trace-pack",
        )

        self.assertIs(result, self.item)
        self.assertIsNotNone(self.item.packed_at)
        self.assertEqual(self.session.begin_calls, 1)
        self.outbound.save_item.assert_awaited_once_with(self.item)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "PACK_GOODS")
        self.assertFalse(audit.before_data["packed"])
        self.assertTrue(audit.after_data["packed"])
        self.assertEqual(audit.trace_id, "trace-pack")

    async def test_pack_in_transaction_requires_outer_transaction(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "requires an active transaction"):
            await self.service.mark_packed_in_transaction(
                101,
            )

        self.outbound.get_item_for_update.assert_not_awaited()

    async def test_repeated_pack_is_idempotent(self) -> None:
        self.session.active = True
        await self.service.mark_packed_in_transaction(101)
        first_packed_at = self.item.packed_at

        result = await self.service.mark_packed_in_transaction(101)

        self.assertIs(result, self.item)
        self.assertEqual(self.item.packed_at, first_packed_at)
        self.outbound.save_item.assert_awaited_once()
        self.audits.append.assert_awaited_once()


class PackingCapabilityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.packing = MagicMock()
        self.packing.mark_packed_in_transaction = AsyncMock()
        self.capability = PackingCapability(self.packing)
        self.task = BusinessTask(
            id=1,
            task_no="PACK-1",
            task_type=TaskType.PACK,
            warehouse_id=1,
            assignee_id=23,
            source_type="OUTBOUND_ORDER_ITEM",
            source_id=101,
        )
        self.item = BusinessTaskItem(
            id=11,
            task_id=1,
            product_id=301,
            planned_quantity=Decimal("8.000"),
        )
        self.employee = Employee(id=23)

    async def test_execute_marks_referenced_goods_as_packed(
        self,
    ) -> None:
        validated = self.capability.validate(
            self.task,
            [self.item],
            {},
        )

        await self.capability.execute(
            self.task,
            self.employee,
            validated,
            "trace-pack",
        )

        self.packing.mark_packed_in_transaction.assert_awaited_once_with(
            101,
            actor_type=ActorType.EMPLOYEE,
            actor_id="23",
            trace_id="trace-pack",
        )
        self.assertIsNone(self.item.actual_quantity)

    async def test_validate_rejects_wrong_source_and_unexpected_data(self) -> None:
        self.task.source_type = "OUTBOUND_ORDER"
        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(self.task, [self.item], {})

        self.task.source_type = "OUTBOUND_ORDER_ITEM"
        with self.assertRaises(InvalidTaskDataError):
            self.capability.validate(self.task, [self.item], {"quantity": 7})


if __name__ == "__main__":
    unittest.main()
