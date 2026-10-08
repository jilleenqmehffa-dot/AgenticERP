import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from pydantic import ValidationError

from app.core.enums import (
    ActorType,
    EmployeeStatus,
    OutboundStatus,
    RecommendationStatus,
    RecommendationType,
    WarehouseLocationType,
)
from app.core.exceptions import (
    InvalidRecommendationStateError,
    InvalidReservationDataError,
    RecommendationReviewPermissionError,
)
from app.models.employee import Employee
from app.models.outbound_order import OutboundOrder
from app.models.outbound_order_item import OutboundOrderItem
from app.models.role import Role
from app.models.stock_reservation import StockReservation
from app.models.task_recommendation import TaskRecommendation
from app.models.warehouse import Warehouse
from app.models.warehouse_location import WarehouseLocation
from app.schemas.reservation_recommendation import ReservationRecommendationCreate
from app.services.outbound.reservation_recommendation import (
    ReservationRecommendationReviewService,
)


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exception_type, exception, traceback):
        return False


class FakeSession:
    def begin(self):
        return FakeTransaction()


class ReservationRecommendationReviewTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.recommendation = TaskRecommendation(
            id=17,
            recommendation_no="REC-17",
            recommendation_type=RecommendationType.RESERVATION,
            task_type=None,
            warehouse_id=1,
            source_type="OUTBOUND_ORDER_ITEM",
            source_id=31,
            rationale="reserve for order",
            proposed_data={
                "quantity": "5.000",
                "location_code": "A-01",
                "lot_no": "LOT-1",
            },
            status=RecommendationStatus.SUGGESTED,
            suggested_by_type=ActorType.AGENT,
            suggested_by_id="planner",
        )
        self.recommendations = MagicMock()
        self.recommendations.get_for_update = AsyncMock(
            return_value=self.recommendation
        )
        self.recommendations.save = AsyncMock(side_effect=lambda value: value)
        self.reviewer = Employee(
            id=9,
            employee_no="E-9",
            name="Manager",
            role_id=1,
            department="Warehouse",
            status=EmployeeStatus.ACTIVE,
        )
        self.reviewer.role = Role(code="MANAGER", name="Manager")
        self.employees = MagicMock()
        self.employees.get_with_role_for_update = AsyncMock(
            return_value=self.reviewer
        )
        self.outbound = MagicMock()
        self.outbound.get_item = AsyncMock(
            return_value=OutboundOrderItem(
                id=31,
                outbound_order_id=21,
                product_id=3,
                requested_quantity=Decimal("5"),
            )
        )
        self.outbound.get_for_update = AsyncMock(
            return_value=OutboundOrder(
                id=21,
                outbound_no="OUT-21",
                warehouse_code="WH-A",
                status=OutboundStatus.PENDING_OUTBOUND,
            )
        )
        self.warehouses = MagicMock()
        self.warehouses.get_by_id = AsyncMock(
            return_value=Warehouse(id=1, code="WH-A", name="Warehouse A")
        )
        self.locations = MagicMock()
        self.locations.get_by_warehouse_and_code = AsyncMock(
            return_value=WarehouseLocation(
                id=2,
                warehouse_id=1,
                code="A-01",
                location_type=WarehouseLocationType.STORAGE,
                is_active=True,
            )
        )
        self.reservations = MagicMock()
        self.reservations.reserve_in_transaction = AsyncMock(
            return_value=StockReservation(id=41, reservation_no="RECOMMENDATION-17")
        )
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda value: value)
        self.service = ReservationRecommendationReviewService(
            FakeSession(),  # type: ignore[arg-type]
            recommendation_repository=self.recommendations,
            employee_repository=self.employees,
            outbound_repository=self.outbound,
            warehouse_repository=self.warehouses,
            location_repository=self.locations,
            reservation_service=self.reservations,
            audit_repository=self.audits,
        )

    async def test_approval_reserves_and_links_result_once(self) -> None:
        result = await self.service.approve(
            recommendation_id=17, reviewer_id=9, reason="approved"
        )
        self.assertEqual(result.status, RecommendationStatus.APPROVED)
        self.assertEqual(result.approved_reservation_id, 41)
        self.assertEqual(result.reviewed_by_id, 9)
        self.assertEqual(
            self.reservations.reserve_in_transaction.await_args.kwargs["quantity"],
            Decimal("5.000"),
        )
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "APPROVE_RESERVATION_RECOMMENDATION")
        self.assertEqual(
            audit.trace_id,
            self.reservations.reserve_in_transaction.await_args.kwargs["trace_id"],
        )

        repeated = await self.service.approve(
            recommendation_id=17, reviewer_id=9, reason="approved again"
        )
        self.assertIs(repeated, result)
        self.reservations.reserve_in_transaction.assert_awaited_once()
        self.audits.append.assert_awaited_once()

    async def test_rejection_records_decision_without_reserving(self) -> None:
        result = await self.service.reject(
            recommendation_id=17, reviewer_id=9, reason="wrong lot"
        )
        self.assertEqual(result.status, RecommendationStatus.REJECTED)
        self.assertEqual(result.review_reason, "wrong lot")
        self.reservations.reserve_in_transaction.assert_not_awaited()
        self.assertEqual(
            self.audits.append.await_args.args[0].action,
            "REJECT_RESERVATION_RECOMMENDATION",
        )
        with self.assertRaises(InvalidRecommendationStateError):
            await self.service.approve(
                recommendation_id=17, reviewer_id=9, reason="changed mind"
            )

    async def test_only_active_manager_may_review(self) -> None:
        self.reviewer.role = Role(code="WORKER", name="Worker")
        with self.assertRaises(RecommendationReviewPermissionError):
            await self.service.approve(
                recommendation_id=17, reviewer_id=9, reason="approved"
            )
        self.reservations.reserve_in_transaction.assert_not_awaited()

    async def test_invalid_proposal_or_location_cannot_reserve(self) -> None:
        self.recommendation.proposed_data = {"quantity": "5.000"}
        with self.assertRaises(InvalidReservationDataError):
            await self.service.approve(
                recommendation_id=17, reviewer_id=9, reason="approved"
            )
        self.recommendation.proposed_data = {
            "quantity": "5.000",
            "location_code": "A-01",
        }
        self.locations.get_by_warehouse_and_code.return_value.is_active = False
        with self.assertRaises(InvalidReservationDataError):
            await self.service.approve(
                recommendation_id=17, reviewer_id=9, reason="approved"
            )
        self.reservations.reserve_in_transaction.assert_not_awaited()

    async def test_agent_creation_schema_requires_reservation_identity(self) -> None:
        values = {
            "recommendation_no": "REC-17",
            "warehouse_id": 1,
            "source_id": 31,
            "rationale": "reserve for order",
            "proposed_data": {"quantity": "5", "location_code": "A-01"},
            "suggested_by_id": "planner",
        }
        proposal = ReservationRecommendationCreate.model_validate(values)
        self.assertEqual(
            proposal.recommendation_type, RecommendationType.RESERVATION
        )
        with self.assertRaises(ValidationError):
            ReservationRecommendationCreate.model_validate(
                {**values, "source_type": "OUTBOUND_ORDER"}
            )
        with self.assertRaises(ValidationError):
            ReservationRecommendationCreate.model_validate(
                {**values, "proposed_data": {"quantity": "5"}}
            )


if __name__ == "__main__":
    unittest.main()
