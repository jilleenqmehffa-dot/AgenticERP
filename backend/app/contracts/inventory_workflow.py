from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class InventoryCountReviewDecision:
    decision: Literal["APPROVE", "REJECT"]
    reason: str
    reviewer_id: int
