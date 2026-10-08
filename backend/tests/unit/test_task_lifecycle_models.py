import unittest

from pydantic import ValidationError
from sqlalchemy import Enum

from app.core.enums import (
    ActorType,
    ExecutionStatus,
    RecommendationStatus,
    RecommendationType,
    SubmissionStatus,
    TaskStatus,
    TaskType,
)
from app.models.business_task import BusinessTask
from app.models.task_execution import TaskExecution
from app.models.task_recommendation import TaskRecommendation
from app.models.task_submission import TaskSubmission
from app.schemas.task_workflow import TaskRecommendationCreate


class TaskLifecycleModelTests(unittest.TestCase):
    def test_lifecycle_enums_separate_each_approval_subject(self) -> None:
        self.assertEqual(
            set(RecommendationStatus),
            {
                RecommendationStatus.SUGGESTED,
                RecommendationStatus.APPROVED,
                RecommendationStatus.REJECTED,
                RecommendationStatus.EXPIRED,
            },
        )
        self.assertEqual(
            set(SubmissionStatus),
            {
                SubmissionStatus.PENDING_REVIEW,
                SubmissionStatus.APPROVED,
                SubmissionStatus.CHANGES_REQUESTED,
                SubmissionStatus.WITHDRAWN,
            },
        )
        self.assertEqual(
            set(ExecutionStatus),
            {
                ExecutionStatus.PENDING,
                ExecutionStatus.RUNNING,
                ExecutionStatus.SUCCEEDED,
                ExecutionStatus.FAILED,
            },
        )

    def test_default_statuses_match_lifecycle_entry_points(self) -> None:
        self.assertEqual(
            BusinessTask.__table__.columns.status.server_default.arg,
            TaskStatus.ASSIGNED.value,
        )
        self.assertEqual(
            TaskRecommendation.__table__.columns.status.server_default.arg,
            RecommendationStatus.SUGGESTED.value,
        )
        self.assertEqual(
            TaskSubmission.__table__.columns.status.server_default.arg,
            SubmissionStatus.PENDING_REVIEW.value,
        )
        self.assertEqual(
            TaskExecution.__table__.columns.status.server_default.arg,
            ExecutionStatus.PENDING.value,
        )

    def test_status_columns_are_constrained_enums(self) -> None:
        for model in (
            BusinessTask,
            TaskRecommendation,
            TaskSubmission,
            TaskExecution,
        ):
            with self.subTest(model=model.__name__):
                self.assertIsInstance(model.__table__.columns.status.type, Enum)

    def test_recommendation_schema_only_accepts_agent_actor(self) -> None:
        data = {
            "recommendation_no": "REC-001",
            "task_type": TaskType.PICK,
            "warehouse_id": 1,
            "rationale": "Sales order is ready to pick",
            "suggested_by_id": "agent-planner",
        }

        recommendation = TaskRecommendationCreate(**data)
        self.assertEqual(recommendation.suggested_by_type, ActorType.AGENT)

        with self.assertRaises(ValidationError):
            TaskRecommendationCreate(
                **data,
                suggested_by_type=ActorType.EMPLOYEE,
            )

    def test_recommendation_source_fields_are_atomic(self) -> None:
        with self.assertRaises(ValidationError):
            TaskRecommendationCreate(
                recommendation_no="REC-001",
                task_type=TaskType.RECEIVE,
                warehouse_id=1,
                source_type="PURCHASE_ORDER",
                rationale="Purchase order is in transit",
                suggested_by_id="agent-planner",
            )

    def test_execution_has_business_idempotency_constraints(self) -> None:
        constraint_names = {
            constraint.name for constraint in TaskExecution.__table__.constraints
        }
        self.assertIn(
            "uq_task_executions_task_submission_capability",
            constraint_names,
        )
        self.assertTrue(TaskExecution.__table__.columns.idempotency_key.unique)

    def test_reservation_recommendation_has_separate_type_and_result_link(self) -> None:
        self.assertEqual(
            TaskRecommendation.__table__.columns.recommendation_type.server_default.arg,
            RecommendationType.TASK.value,
        )
        self.assertTrue(TaskRecommendation.__table__.columns.task_type.nullable)
        constraint_names = {
            constraint.name for constraint in TaskRecommendation.__table__.constraints
        }
        self.assertIn("ck_task_recommendations_type_source", constraint_names)
        self.assertIn(
            "uq_task_recommendations_approved_reservation", constraint_names
        )


if __name__ == "__main__":
    unittest.main()
