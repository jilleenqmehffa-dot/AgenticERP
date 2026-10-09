import unittest
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.api.inventory_adjustments import _reviewer_id
from app.core.enums import AdjustmentStatus, TaskStatus
from app.core.exceptions import InvalidAdjustmentStateError
from app.db.session import get_db_session
from app.main import app
from app.models.business_task import BusinessTask
from app.models.inventory_adjustment import InventoryAdjustment


class InventoryAdjustmentApiTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_list_request_and_publish_review_task(self) -> None:
        adjustment = InventoryAdjustment(
            id=51, count_item_id=11, difference_quantity=Decimal("-2"),
            status=AdjustmentStatus.PENDING_REVIEW,
        )
        task = BusinessTask(id=201, task_no="COUNT-REVIEW-51", status=TaskStatus.ASSIGNED)
        with patch("app.api.inventory_adjustments.InventoryCountWorkflow") as workflow_type:
            workflow_type.return_value.list_requests = AsyncMock(return_value=[adjustment])
            listed = await self.client.get("/inventory-adjustments")
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(listed.json()[0]["difference_quantity"], "-2")
            workflow_type.return_value.publish_review_task = AsyncMock(return_value=task)
            published = await self.client.post(
                "/inventory-adjustments/51/review-task", json={"assignee_id": 9}
            )
        self.assertEqual(published.status_code, 200)
        self.assertEqual(published.json()["task_no"], "COUNT-REVIEW-51")

    async def test_cannot_publish_adjustment_before_review_task_completes(self) -> None:
        with patch("app.api.inventory_adjustments.InventoryCountWorkflow") as workflow_type:
            workflow_type.return_value.publish_adjustment_task = AsyncMock(
                side_effect=InvalidAdjustmentStateError("review incomplete")
            )
            response = await self.client.post(
                "/inventory-adjustments/51/adjustment-task", json={"assignee_id": 24}
            )
        self.assertEqual(response.status_code, 409)

    async def test_review_requires_authentication(self) -> None:
        app.dependency_overrides.pop(_reviewer_id)
        response = await self.client.get("/inventory-adjustments")
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
