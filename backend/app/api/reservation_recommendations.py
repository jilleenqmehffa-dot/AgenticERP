from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InvalidCredentialsError,
    InvalidRecommendationStateError,
    InventoryError,
    RecommendationNotFoundError,
    RecommendationReviewPermissionError,
)
from app.db.session import get_db_session
from app.schemas.reservation_recommendation import (
    ReservationRecommendationReview,
    ReservationRecommendationReviewResult,
)
from app.services.auth.account import AccountService
from app.services.outbound.reservation_recommendation import (
    ReservationRecommendationReviewService,
)

router = APIRouter(prefix="/reservation-recommendations", tags=["reservations"])
_basic = HTTPBasic()


async def _reviewer_id(
    credentials: HTTPBasicCredentials = Depends(_basic),
    session: AsyncSession = Depends(get_db_session),
) -> int:
    try:
        authenticated = await AccountService(session).authenticate(
            credentials.username, credentials.password
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        ) from None
    return authenticated.employee_id


def _review_error(error: Exception) -> HTTPException:
    if isinstance(error, RecommendationNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, RecommendationReviewPermissionError):
        return HTTPException(status_code=403, detail=str(error))
    if isinstance(error, InvalidRecommendationStateError):
        return HTTPException(status_code=409, detail=str(error))
    return HTTPException(status_code=422, detail=str(error))


@router.post(
    "/{recommendation_id}/approve",
    response_model=ReservationRecommendationReviewResult,
)
async def approve_reservation_recommendation(
    recommendation_id: int,
    request: ReservationRecommendationReview,
    reviewer_id: int = Depends(_reviewer_id),
    session: AsyncSession = Depends(get_db_session),
) -> ReservationRecommendationReviewResult:
    try:
        recommendation = await ReservationRecommendationReviewService(session).approve(
            recommendation_id=recommendation_id,
            reviewer_id=reviewer_id,
            reason=request.reason,
        )
    except (
        RecommendationNotFoundError,
        RecommendationReviewPermissionError,
        InvalidRecommendationStateError,
        InventoryError,
        ValueError,
    ) as error:
        raise _review_error(error) from None
    return ReservationRecommendationReviewResult.model_validate(
        {
            "recommendation_id": recommendation.id,
            "status": recommendation.status,
            "reviewed_by_id": recommendation.reviewed_by_id,
            "reviewed_at": recommendation.reviewed_at,
            "review_reason": recommendation.review_reason,
            "approved_reservation_id": recommendation.approved_reservation_id,
        }
    )


@router.post(
    "/{recommendation_id}/reject",
    response_model=ReservationRecommendationReviewResult,
)
async def reject_reservation_recommendation(
    recommendation_id: int,
    request: ReservationRecommendationReview,
    reviewer_id: int = Depends(_reviewer_id),
    session: AsyncSession = Depends(get_db_session),
) -> ReservationRecommendationReviewResult:
    try:
        recommendation = await ReservationRecommendationReviewService(session).reject(
            recommendation_id=recommendation_id,
            reviewer_id=reviewer_id,
            reason=request.reason,
        )
    except (
        RecommendationNotFoundError,
        RecommendationReviewPermissionError,
        InvalidRecommendationStateError,
        ValueError,
    ) as error:
        raise _review_error(error) from None
    return ReservationRecommendationReviewResult.model_validate(
        {
            "recommendation_id": recommendation.id,
            "status": recommendation.status,
            "reviewed_by_id": recommendation.reviewed_by_id,
            "reviewed_at": recommendation.reviewed_at,
            "review_reason": recommendation.review_reason,
            "approved_reservation_id": recommendation.approved_reservation_id,
        }
    )
