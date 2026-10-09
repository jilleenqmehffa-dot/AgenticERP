import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

from app.core.enums import RecommendationStatus
from app.core.exceptions import InvalidReservationDataError
from app.schemas.reservation_recommendation import ReservationRecommendationCreate
from app.workflows.reservation import ReservationWorkflow


class FakeTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False


class ReservationWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        session = MagicMock()
        session.begin.return_value = FakeTransaction()
        self.recommendations = MagicMock()
        self.recommendations.get_by_no_for_update = AsyncMock(return_value=None)

        async def save(value):
            value.id = 11
            return value

        self.recommendations.save = AsyncMock(side_effect=save)
        self.reviews = MagicMock()
        self.reviews.approve = AsyncMock()
        self.reviews.reject = AsyncMock()
        self.audits = MagicMock()
        self.audits.append = AsyncMock()
        self.workflow = ReservationWorkflow(
            session,
            recommendation_repository=self.recommendations,
            review_service=self.reviews,
            audit_repository=self.audits,
        )
        self.proposal = ReservationRecommendationCreate(
            recommendation_no="REC-11",
            warehouse_id=1,
            source_id=2,
            rationale="available stock",
            confidence=Decimal("0.9000"),
            proposed_data={"quantity": "5", "location_code": "A-01"},
            suggested_by_id="planner",
        )

    async def test_suggestion_is_pending_and_idempotent(self) -> None:
        result = await self.workflow.suggest(self.proposal)
        self.assertEqual(result.status, RecommendationStatus.SUGGESTED)
        self.assertIsNone(result.approved_reservation_id)
        self.assertEqual(self.audits.append.await_args.args[0].action, "SUGGEST_RESERVATION")

        self.recommendations.get_by_no_for_update.return_value = result
        repeated = await self.workflow.suggest(self.proposal)
        self.assertIs(repeated, result)
        self.recommendations.save.assert_awaited_once()

    async def test_reused_number_with_other_content_is_rejected(self) -> None:
        existing = await self.workflow.suggest(self.proposal)
        self.recommendations.get_by_no_for_update.return_value = existing
        changed = self.proposal.model_copy(update={"rationale": "other stock"})
        with self.assertRaises(InvalidReservationDataError):
            await self.workflow.suggest(changed)

    async def test_review_is_delegated_to_controlled_service(self) -> None:
        await self.workflow.approve(recommendation_id=11, reviewer_id=9, reason="ok")
        self.reviews.approve.assert_awaited_once_with(
            recommendation_id=11, reviewer_id=9, reason="ok"
        )
        await self.workflow.reject(recommendation_id=11, reviewer_id=9, reason="bad lot")
        self.reviews.reject.assert_awaited_once_with(
            recommendation_id=11, reviewer_id=9, reason="bad lot"
        )


if __name__ == "__main__":
    unittest.main()
