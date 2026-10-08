from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    EmployeeStatus,
    RecommendationStatus,
    RecommendationType,
    WarehouseLocationType,
)
from app.core.exceptions import (
    InvalidRecommendationStateError,
    InvalidReservationDataError,
    RecommendationNotFoundError,
    RecommendationReviewPermissionError,
)
from app.core.validation import positive_int, required_text
from app.models.audit_log import AuditLog
from app.models.employee import Employee
from app.models.task_recommendation import TaskRecommendation
from app.repositories.audit_log import AuditLogRepository
from app.repositories.employee import EmployeeRepository
from app.repositories.outbound_order import OutboundOrderRepository
from app.repositories.task_recommendation import TaskRecommendationRepository
from app.repositories.warehouse import WarehouseRepository
from app.repositories.warehouse_location import WarehouseLocationRepository
from app.schemas.reservation_recommendation import ReservationProposal
from app.services.outbound.reservation import ReservationService


class ReservationRecommendationReviewService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        recommendation_repository: TaskRecommendationRepository | None = None,
        employee_repository: EmployeeRepository | None = None,
        outbound_repository: OutboundOrderRepository | None = None,
        warehouse_repository: WarehouseRepository | None = None,
        location_repository: WarehouseLocationRepository | None = None,
        reservation_service: ReservationService | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._recommendations = recommendation_repository or TaskRecommendationRepository(
            session
        )
        self._employees = employee_repository or EmployeeRepository(session)
        self._outbound = outbound_repository or OutboundOrderRepository(session)
        self._warehouses = warehouse_repository or WarehouseRepository(session)
        self._locations = location_repository or WarehouseLocationRepository(session)
        self._reservations = reservation_service or ReservationService(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def approve(
        self, *, recommendation_id: int, reviewer_id: int, reason: str
    ) -> TaskRecommendation:
        recommendation_id = positive_int(recommendation_id, "recommendation_id")
        reviewer_id = positive_int(reviewer_id, "reviewer_id")
        reason = required_text(reason, "reason")
        async with self._session.begin():
            recommendation = await self._get_reservation_recommendation(
                recommendation_id
            )
            reviewer = await self._get_reviewer(reviewer_id)
            if recommendation.status == RecommendationStatus.APPROVED:
                if recommendation.approved_reservation_id is None:
                    raise InvalidRecommendationStateError(
                        "approved recommendation has no reservation"
                    )
                return recommendation
            self._require_suggested(recommendation)
            proposal = self._parse_proposal(recommendation)
            await self._validate_source(recommendation, proposal)

            trace_id = str(uuid4())
            reservation = await self._reservations.reserve_in_transaction(
                reservation_no=f"RECOMMENDATION-{recommendation.id}",
                outbound_order_item_id=recommendation.source_id,
                quantity=proposal.quantity,
                location_code=proposal.location_code,
                lot_no=proposal.lot_no,
                expires_at=proposal.expires_at,
                actor_type=ActorType.EMPLOYEE,
                actor_id=str(reviewer.id),
                trace_id=trace_id,
            )
            recommendation.status = RecommendationStatus.APPROVED
            recommendation.reviewed_by_id = reviewer.id
            recommendation.review_reason = reason
            recommendation.reviewed_at = datetime.now(timezone.utc)
            recommendation.approved_reservation_id = reservation.id
            await self._recommendations.save(recommendation)
            await self._audits.append(
                self._review_audit(
                    recommendation,
                    reviewer,
                    action="APPROVE_RESERVATION_RECOMMENDATION",
                    trace_id=trace_id,
                )
            )
            return recommendation

    async def reject(
        self, *, recommendation_id: int, reviewer_id: int, reason: str
    ) -> TaskRecommendation:
        recommendation_id = positive_int(recommendation_id, "recommendation_id")
        reviewer_id = positive_int(reviewer_id, "reviewer_id")
        reason = required_text(reason, "reason")
        async with self._session.begin():
            recommendation = await self._get_reservation_recommendation(
                recommendation_id
            )
            reviewer = await self._get_reviewer(reviewer_id)
            if recommendation.status == RecommendationStatus.REJECTED:
                return recommendation
            self._require_suggested(recommendation)
            recommendation.status = RecommendationStatus.REJECTED
            recommendation.reviewed_by_id = reviewer.id
            recommendation.review_reason = reason
            recommendation.reviewed_at = datetime.now(timezone.utc)
            await self._recommendations.save(recommendation)
            await self._audits.append(
                self._review_audit(
                    recommendation,
                    reviewer,
                    action="REJECT_RESERVATION_RECOMMENDATION",
                    trace_id=str(uuid4()),
                )
            )
            return recommendation

    async def _get_reservation_recommendation(
        self, recommendation_id: int
    ) -> TaskRecommendation:
        recommendation = await self._recommendations.get_for_update(recommendation_id)
        if recommendation is None:
            raise RecommendationNotFoundError(recommendation_id)
        if recommendation.recommendation_type != RecommendationType.RESERVATION:
            raise InvalidRecommendationStateError(
                "recommendation is not a reservation proposal"
            )
        return recommendation

    async def _get_reviewer(self, reviewer_id: int) -> Employee:
        reviewer = await self._employees.get_with_role_for_update(reviewer_id)
        if (
            reviewer is None
            or reviewer.status != EmployeeStatus.ACTIVE
            or reviewer.role is None
            or reviewer.role.code != "MANAGER"
        ):
            raise RecommendationReviewPermissionError(
                f"employee cannot review reservation recommendations: {reviewer_id}"
            )
        return reviewer

    @staticmethod
    def _require_suggested(recommendation: TaskRecommendation) -> None:
        if recommendation.status != RecommendationStatus.SUGGESTED:
            raise InvalidRecommendationStateError(
                "recommendation is not awaiting review"
            )

    @staticmethod
    def _parse_proposal(recommendation: TaskRecommendation) -> ReservationProposal:
        try:
            return ReservationProposal.model_validate(recommendation.proposed_data)
        except ValidationError:
            raise InvalidReservationDataError(
                "reservation recommendation data is invalid"
            ) from None

    async def _validate_source(
        self, recommendation: TaskRecommendation, proposal: ReservationProposal
    ) -> None:
        if (
            recommendation.source_type != "OUTBOUND_ORDER_ITEM"
            or recommendation.source_id is None
            or recommendation.task_type is not None
            or recommendation.approved_task_id is not None
            or recommendation.suggested_by_type != ActorType.AGENT
        ):
            raise InvalidReservationDataError(
                "reservation recommendation source is invalid"
            )
        warehouse = await self._warehouses.get_by_id(recommendation.warehouse_id)
        item = await self._outbound.get_item(recommendation.source_id)
        if warehouse is None or item is None:
            raise InvalidReservationDataError(
                "reservation recommendation source does not exist"
            )
        order = await self._outbound.get_for_update(item.outbound_order_id)
        if order is None or order.warehouse_code != warehouse.code:
            raise InvalidReservationDataError(
                "reservation recommendation warehouse does not match outbound order"
            )
        location = await self._locations.get_by_warehouse_and_code(
            warehouse.id, proposal.location_code
        )
        if (
            location is None
            or not location.is_active
            or location.location_type != WarehouseLocationType.STORAGE
        ):
            raise InvalidReservationDataError(
                "reservation source location must be an active storage location"
            )

    @staticmethod
    def _review_audit(
        recommendation: TaskRecommendation,
        reviewer: Employee,
        *,
        action: str,
        trace_id: str,
    ) -> AuditLog:
        return AuditLog(
            actor_type=ActorType.EMPLOYEE,
            actor_id=str(reviewer.id),
            action=action,
            entity_type="TASK_RECOMMENDATION",
            entity_id=str(recommendation.id),
            before_data={"status": RecommendationStatus.SUGGESTED.value},
            after_data={
                "status": recommendation.status.value,
                "review_reason": recommendation.review_reason,
                "approved_reservation_id": recommendation.approved_reservation_id,
            },
            trace_id=trace_id,
            metadata_={"recommendation_type": RecommendationType.RESERVATION.value},
        )
