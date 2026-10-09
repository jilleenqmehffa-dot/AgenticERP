from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AdjustmentStatus
from app.core.exceptions import (
    AdjustmentNotFoundError,
    AdjustmentReviewPermissionError,
    InvalidAdjustmentStateError,
    InvalidCredentialsError,
)
from app.db.session import get_db_session
from app.schemas.inventory_adjustment import (
    InventoryAdjustmentRead,
    PublishInventoryTask,
    PublishedInventoryTask,
)
from app.services.auth.account import AccountService
from app.workflows.inventory_count import InventoryCountWorkflow


router = APIRouter(prefix="/inventory-adjustments", tags=["inventory"])
_basic = HTTPBasic()


async def _reviewer_id(
    credentials: HTTPBasicCredentials = Depends(_basic),
    session: AsyncSession = Depends(get_db_session),
) -> int:
    try:
        account = await AccountService(session).authenticate(
            credentials.username, credentials.password
        )
    except InvalidCredentialsError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        ) from None
    return account.employee_id


def _error(error: Exception) -> HTTPException:
    if isinstance(error, AdjustmentNotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, AdjustmentReviewPermissionError):
        return HTTPException(status_code=403, detail=str(error))
    return HTTPException(status_code=409, detail=str(error))


@router.get("", response_model=list[InventoryAdjustmentRead])
async def list_inventory_task_requests(
    request_status: AdjustmentStatus = AdjustmentStatus.PENDING_REVIEW,
    reviewer_id: int = Depends(_reviewer_id),
    session: AsyncSession = Depends(get_db_session),
) -> list[InventoryAdjustmentRead]:
    try:
        requests = await InventoryCountWorkflow(session).list_requests(
            reviewer_id=reviewer_id, status=request_status
        )
    except (AdjustmentReviewPermissionError, InvalidAdjustmentStateError, ValueError) as error:
        raise _error(error) from None
    return [InventoryAdjustmentRead.model_validate(request) for request in requests]


@router.post("/{adjustment_id}/review-task", response_model=PublishedInventoryTask)
async def publish_inventory_review_task(
    adjustment_id: int,
    request: PublishInventoryTask,
    publisher_id: int = Depends(_reviewer_id),
    session: AsyncSession = Depends(get_db_session),
) -> PublishedInventoryTask:
    try:
        task = await InventoryCountWorkflow(session).publish_review_task(
            adjustment_id=adjustment_id,
            assignee_id=request.assignee_id,
            publisher_id=publisher_id,
        )
    except (AdjustmentNotFoundError, AdjustmentReviewPermissionError, InvalidAdjustmentStateError, ValueError) as error:
        raise _error(error) from None
    return PublishedInventoryTask.model_validate(task, from_attributes=True)


@router.post("/{adjustment_id}/adjustment-task", response_model=PublishedInventoryTask)
async def publish_inventory_adjustment_task(
    adjustment_id: int,
    request: PublishInventoryTask,
    publisher_id: int = Depends(_reviewer_id),
    session: AsyncSession = Depends(get_db_session),
) -> PublishedInventoryTask:
    try:
        task = await InventoryCountWorkflow(session).publish_adjustment_task(
            adjustment_id=adjustment_id,
            assignee_id=request.assignee_id,
            publisher_id=publisher_id,
        )
    except (AdjustmentNotFoundError, AdjustmentReviewPermissionError, InvalidAdjustmentStateError, ValueError) as error:
        raise _error(error) from None
    return PublishedInventoryTask.model_validate(task, from_attributes=True)
