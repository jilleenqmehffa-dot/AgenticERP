import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.api.reservation_recommendations import _reviewer_id
from app.core.enums import RecommendationStatus
from app.core.exceptions import InvalidRecommendationStateError
from app.db.session import get_db_session
from app.main import app
from app.models.task_recommendation import TaskRecommendation


class ReservationRecommendationApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        async def reviewer() -> int:
            return 9

        async def session():
            yield object()

        app.dependency_overrides[_reviewer_id] = reviewer
        app.dependency_overrides[get_db_session] = session
        self.client = AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        app.dependency_overrides.clear()

    async def test_approve_endpoint_returns_linked_reservation(self) -> None:
        recommendation = TaskRecommendation(
            id=17,
            status=RecommendationStatus.APPROVED,
            reviewed_by_id=9,
            reviewed_at=datetime.now(timezone.utc),
            review_reason="approved",
            approved_reservation_id=41,
        )
        with patch(
            "app.api.reservation_recommendations.ReservationWorkflow"
        ) as workflow_type:
            workflow_type.return_value.approve = AsyncMock(return_value=recommendation)
            response = await self.client.post(
                "/reservation-recommendations/17/approve",
                json={"reason": "approved"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["approved_reservation_id"], 41)
        self.assertEqual(response.json()["status"], "APPROVED")

    async def test_conflicting_decision_returns_409(self) -> None:
        with patch(
            "app.api.reservation_recommendations.ReservationWorkflow"
        ) as workflow_type:
            workflow_type.return_value.reject = AsyncMock(
                side_effect=InvalidRecommendationStateError("already approved")
            )
            response = await self.client.post(
                "/reservation-recommendations/17/reject",
                json={"reason": "no"},
            )
        self.assertEqual(response.status_code, 409)

    async def test_review_requires_http_basic_credentials(self) -> None:
        app.dependency_overrides.pop(_reviewer_id)
        response = await self.client.post(
            "/reservation-recommendations/17/approve",
            json={"reason": "approved"},
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Basic")


if __name__ == "__main__":
    unittest.main()
