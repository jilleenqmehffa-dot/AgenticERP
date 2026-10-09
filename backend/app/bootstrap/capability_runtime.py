from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.capabilities.dispatcher import CapabilityDispatcher
from app.repositories.audit_log import AuditLogRepository
from app.repositories.business_task import BusinessTaskRepository
from app.repositories.outbound_order import OutboundOrderRepository
from app.repositories.stock_reservation import StockReservationRepository
from app.services.inbound.receiving import ReceivingService
from app.services.inventory.balance import InventoryBalanceService
from app.services.inventory.bucket import InventoryBucketService
from app.services.inventory.counting import InventoryCountService
from app.services.inventory.movement import InventoryMovementService
from app.services.outbound.packing import PackingService
from app.services.outbound.picking import PickingService
from app.services.outbound.reservation import ReservationService
from app.services.tasks.execution import CapabilityExecutionService
from app.workflows.inbound import InboundWorkflow
from app.workflows.inventory_count import InventoryCountWorkflow
from app.workflows.outbound import OutboundWorkflow
from app.workflows.reservation import ReservationWorkflow


@dataclass(frozen=True, slots=True)
class CapabilityRuntime:
    dispatcher: CapabilityDispatcher
    inbound_workflow: InboundWorkflow
    inventory_count_workflow: InventoryCountWorkflow
    reservation_workflow: ReservationWorkflow
    outbound_workflow: OutboundWorkflow


def build_capability_runtime(
    session: AsyncSession,
    *,
    task_repository: BusinessTaskRepository,
    audit_repository: AuditLogRepository,
) -> CapabilityRuntime:
    balances = InventoryBalanceService(session)
    movements = InventoryMovementService(session, balance_service=balances)
    buckets = InventoryBucketService(session)
    reservations = StockReservationRepository(session)
    outbound = OutboundOrderRepository(session)
    reservation_service = ReservationService(
        session,
        reservation_repository=reservations,
        outbound_repository=outbound,
        bucket_service=buckets,
        balance_service=balances,
    )
    inventory_count_workflow = InventoryCountWorkflow(
        session,
        task_repository=task_repository,
        audit_repository=audit_repository,
        bucket_service=buckets,
        movement_service=movements,
    )
    dispatcher = CapabilityDispatcher(
        movements,
        PackingService(session, outbound_repository=outbound),
        ReceivingService(session),
        buckets,
        PickingService(
            session,
            reservation_repository=reservations,
            outbound_repository=outbound,
            bucket_service=buckets,
        ),
        reservation_service,
        reservations,
        outbound,
        InventoryCountService(
            session,
            task_repository=task_repository,
            audit_repository=audit_repository,
        ),
        inventory_count_workflow,
    )
    return CapabilityRuntime(
        dispatcher=dispatcher,
        inbound_workflow=InboundWorkflow(
            session,
            audit_repository=audit_repository,
        ),
        inventory_count_workflow=inventory_count_workflow,
        reservation_workflow=ReservationWorkflow(
            session,
            audit_repository=audit_repository,
        ),
        outbound_workflow=OutboundWorkflow(
            session,
            outbound_repository=outbound,
            reservation_repository=reservations,
        ),
    )


def build_capability_execution_service(
    session: AsyncSession,
) -> CapabilityExecutionService:
    tasks = BusinessTaskRepository(session)
    audits = AuditLogRepository(session)
    runtime = build_capability_runtime(
        session,
        task_repository=tasks,
        audit_repository=audits,
    )
    return CapabilityExecutionService(
        session,
        task_repository=tasks,
        audit_repository=audits,
        dispatcher=runtime.dispatcher,
        inbound_workflow=runtime.inbound_workflow,
        inventory_count_workflow=runtime.inventory_count_workflow,
        outbound_workflow=runtime.outbound_workflow,
    )
