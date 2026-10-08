from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ActorType, RecommendationStatus, RecommendationType


class ReservationProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    location_code: str = Field(min_length=1, max_length=64)
    lot_no: str = Field(default="", max_length=100)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_expiry(self) -> "ReservationProposal":
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        return self


class ReservationRecommendationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation_no: str = Field(min_length=1, max_length=64)
    recommendation_type: RecommendationType = RecommendationType.RESERVATION
    warehouse_id: int = Field(gt=0)
    source_type: str = "OUTBOUND_ORDER_ITEM"
    source_id: int = Field(gt=0)
    rationale: str = Field(min_length=1)
    confidence: Decimal | None = Field(default=None, ge=0, le=1)
    proposed_data: ReservationProposal
    suggested_by_type: ActorType = ActorType.AGENT
    suggested_by_id: str = Field(min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_kind(self) -> "ReservationRecommendationCreate":
        if (
            self.recommendation_type != RecommendationType.RESERVATION
            or self.source_type != "OUTBOUND_ORDER_ITEM"
            or self.suggested_by_type != ActorType.AGENT
        ):
            raise ValueError("invalid reservation recommendation identity")
        return self


class ReservationRecommendationReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1)


class ReservationRecommendationReviewResult(BaseModel):
    recommendation_id: int
    status: RecommendationStatus
    reviewed_by_id: int
    reviewed_at: datetime
    review_reason: str
    approved_reservation_id: int | None
