from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    ActorType,
    DispatchRequestStatus,
    StockStatus,
    TaskType,
    WarehouseLocationType,
)
from app.core.exceptions import InvalidTaskDataError
from app.domain.inbound.contracts import ReceivingResult
from app.domain.inbound.policies import (
    get_putaway_route,
    putaway_generation_key,
)
from app.models.audit_log import AuditLog
from app.models.business_task import BusinessTask
from app.models.putaway_dispatch_request import PutawayDispatchRequest
from app.repositories.audit_log import AuditLogRepository
from app.repositories.putaway_dispatch import PutawayDispatchRepository
from app.services.inbound.completion import InboundCompletionService


class InboundWorkflow:
    PUTAWAY_SOURCE_TYPE = "PUTAWAY_DISPATCH"

    def __init__(
        self,
        session: AsyncSession,
        dispatch_repository: PutawayDispatchRepository | None = None,
        completion_service: InboundCompletionService | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._dispatches = dispatch_repository or PutawayDispatchRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)
        self._completion = completion_service or InboundCompletionService(
            session,
            dispatch_repository=self._dispatches,
            audit_repository=self._audits,
        )

    async def after_task_completed_in_transaction(
        self,
        task: BusinessTask,
        capability_result: object,
        *,
        trace_id: str,
    ) -> None:
        if not self._session.in_transaction():
            raise RuntimeError(
                "after_task_completed_in_transaction requires an active transaction"
            )
        if task.task_type == TaskType.RECEIVE:
            if not isinstance(capability_result, ReceivingResult):
                raise InvalidTaskDataError(
                    "RECEIVE capability must return ReceivingResult"
                )
            await self._after_receive(capability_result, trace_id=trace_id)
            return
        if (
            task.task_type == TaskType.PUTAWAY
            and task.source_type == self.PUTAWAY_SOURCE_TYPE
        ):
            if task.source_id is None:
                raise InvalidTaskDataError(
                    "dispatch PUTAWAY task must reference a dispatch request"
                )
            await self._completion.try_complete_for_dispatch_in_transaction(
                task.source_id,
                trace_id=trace_id,
            )

    async def _after_receive(
        self,
        result: ReceivingResult,
        *,
        trace_id: str,
    ) -> None:
        for disposition in result.dispositions:
            route = get_putaway_route(disposition.stock_status)
            if route is None:
                raise InvalidTaskDataError(
                    f"unsupported receiving disposition: {disposition.stock_status}"
                )
            location_type = route.required_location_type
            target_status = route.target_stock_status
            generation_key = putaway_generation_key(
                result.inspection_id,
                disposition.stock_status,
            )
            request = await self._dispatches.get_by_generation_key(generation_key)
            if request is not None:
                self._validate_existing_request(
                    request,
                    result=result,
                    bucket_id=disposition.bucket_id,
                    location_type=location_type,
                    target_status=target_status,
                    quantity=disposition.quantity,
                )
                continue
            request = await self._dispatches.save(
                PutawayDispatchRequest(
                    inspection_id=result.inspection_id,
                    source_bucket_id=disposition.bucket_id,
                    warehouse_id=result.warehouse_id,
                    from_location_id=result.receiving_location_id,
                    required_location_type=location_type,
                    target_stock_status=target_status,
                    planned_quantity=disposition.quantity,
                    generation_key=generation_key,
                    status=DispatchRequestStatus.PENDING,
                )
            )
            await self._audits.append(
                AuditLog(
                    actor_type=ActorType.SYSTEM,
                    actor_id="INBOUND_WORKFLOW",
                    action="CREATE_PUTAWAY_DISPATCH_REQUEST",
                    entity_type="PUTAWAY_DISPATCH_REQUEST",
                    entity_id=str(request.id),
                    before_data={},
                    after_data={
                        "generation_key": generation_key,
                        "status": DispatchRequestStatus.PENDING.value,
                        "source_bucket_id": disposition.bucket_id,
                        "planned_quantity": str(disposition.quantity),
                    },
                    trace_id=trace_id,
                    metadata_={
                        "receipt_id": result.receipt_id,
                        "receipt_item_id": result.receipt_item_id,
                        "inspection_id": result.inspection_id,
                    },
                )
            )

        await self._completion.try_complete_receipt_in_transaction(
            result.receipt_id,
            trace_id=trace_id,
        )

    @staticmethod
    def _validate_existing_request(
        request: PutawayDispatchRequest,
        *,
        result: ReceivingResult,
        bucket_id: int,
        location_type: WarehouseLocationType,
        target_status: StockStatus,
        quantity: object,
    ) -> None:
        expected = (
            result.inspection_id,
            bucket_id,
            result.warehouse_id,
            result.receiving_location_id,
            location_type,
            target_status,
            quantity,
        )
        actual = (
            request.inspection_id,
            request.source_bucket_id,
            request.warehouse_id,
            request.from_location_id,
            request.required_location_type,
            request.target_stock_status,
            request.planned_quantity,
        )
        if actual != expected:
            raise InvalidTaskDataError(
                "generation key already belongs to a different dispatch request"
            )
