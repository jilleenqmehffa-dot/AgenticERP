from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, RecommendationStatus, RecommendationType
from app.core.exceptions import InvalidReservationDataError
from app.models.audit_log import AuditLog
from app.models.task_recommendation import TaskRecommendation
from app.repositories.audit_log import AuditLogRepository
from app.repositories.task_recommendation import TaskRecommendationRepository
from app.schemas.reservation_recommendation import ReservationRecommendationCreate
from app.services.outbound.reservation_recommendation import (
    ReservationRecommendationReviewService,
)


class ReservationWorkflow:
    """Agent proposal -> manager decision -> controlled stock reservation."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        recommendation_repository: TaskRecommendationRepository | None = None,
        review_service: ReservationRecommendationReviewService | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._recommendations = recommendation_repository or TaskRecommendationRepository(session)
        self._reviews = review_service or ReservationRecommendationReviewService(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def suggest(
        self, proposal: ReservationRecommendationCreate
    ) -> TaskRecommendation:
        proposal = ReservationRecommendationCreate.model_validate(proposal)
        async with self._session.begin():
            existing = await self._recommendations.get_by_no_for_update(
                proposal.recommendation_no
            )
            if existing is not None:
                if self._matches(existing, proposal):
                    return existing
                raise InvalidReservationDataError(
                    "recommendation number belongs to a different proposal"
                )
            recommendation = await self._recommendations.save(
                TaskRecommendation(
                    recommendation_no=proposal.recommendation_no,
                    recommendation_type=RecommendationType.RESERVATION,
                    task_type=None,
                    warehouse_id=proposal.warehouse_id,
                    source_type=proposal.source_type,
                    source_id=proposal.source_id,
                    rationale=proposal.rationale,
                    confidence=proposal.confidence,
                    proposed_data=proposal.proposed_data.model_dump(mode="json"),
                    status=RecommendationStatus.SUGGESTED,
                    suggested_by_type=ActorType.AGENT,
                    suggested_by_id=proposal.suggested_by_id,
                )
            )
            await self._audits.append(
                AuditLog(
                    actor_type=ActorType.AGENT,
                    actor_id=proposal.suggested_by_id,
                    action="SUGGEST_RESERVATION",
                    entity_type="TASK_RECOMMENDATION",
                    entity_id=str(recommendation.id),
                    before_data={},
                    after_data={"status": RecommendationStatus.SUGGESTED.value},
                    trace_id=str(uuid4()),
                    metadata_={
                        "recommendation_type": RecommendationType.RESERVATION.value,
                        "outbound_order_item_id": proposal.source_id,
                    },
                )
            )
            return recommendation

    async def approve(
        self, *, recommendation_id: int, reviewer_id: int, reason: str
    ) -> TaskRecommendation:
        return await self._reviews.approve(
            recommendation_id=recommendation_id,
            reviewer_id=reviewer_id,
            reason=reason,
        )

    async def reject(
        self, *, recommendation_id: int, reviewer_id: int, reason: str
    ) -> TaskRecommendation:
        return await self._reviews.reject(
            recommendation_id=recommendation_id,
            reviewer_id=reviewer_id,
            reason=reason,
        )

    @staticmethod
    def _matches(
        existing: TaskRecommendation, proposal: ReservationRecommendationCreate
    ) -> bool:
        return (
            existing.recommendation_type == RecommendationType.RESERVATION
            and existing.task_type is None
            and existing.warehouse_id == proposal.warehouse_id
            and existing.source_type == proposal.source_type
            and existing.source_id == proposal.source_id
            and existing.rationale == proposal.rationale
            and existing.confidence == proposal.confidence
            and existing.proposed_data == proposal.proposed_data.model_dump(mode="json")
            and existing.suggested_by_type == ActorType.AGENT
            and existing.suggested_by_id == proposal.suggested_by_id
        )
