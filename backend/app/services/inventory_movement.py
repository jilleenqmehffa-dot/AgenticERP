from decimal import Decimal
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType, MovementType
from app.core.exceptions import InvalidInventoryDataError
from app.models.audit_log import AuditLog
from app.models.inventory import Inventory
from app.models.stock_movement import StockMovement
from app.repositories.audit_log import AuditLogRepository
from app.repositories.inventory import InventoryRepository
from app.repositories.stock_movement import StockMovementRepository
from app.services.inventory_balance import InventoryBalanceService


class InventoryMovementService:
    def __init__(
        self,
        session: AsyncSession,
        inventory_repository: InventoryRepository | None = None,
        movement_repository: StockMovementRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
        balance_service: InventoryBalanceService | None = None,
    ) -> None:
        self._session = session
        self._balances = balance_service or InventoryBalanceService(
            session,
            inventory_repository,
        )
        self._movements = movement_repository or StockMovementRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def stock_in(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> Inventory:
        product_id = self._validate_product_id(product_id)
        warehouse_code = self._validate_warehouse_code(warehouse_code)
        stock_quantity = self._validate_quantity(quantity)
        reference_type, reference_id = self._validate_reference(
            reference_type, reference_id
        )
        created_by = self._optional_identifier(created_by, "created_by")
        audit_actor_id = self._audit_actor_id(actor_type, actor_id)
        trace_id = self._trace_id(trace_id)

        async with self._session.begin():
            return await self._stock_in(
                product_id,
                warehouse_code,
                stock_quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=created_by,
                actor_type=actor_type,
                actor_id=audit_actor_id,
                trace_id=trace_id,
            )

    async def stock_out(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> Inventory:
        product_id = self._validate_product_id(product_id)
        warehouse_code = self._validate_warehouse_code(warehouse_code)
        stock_quantity = self._validate_quantity(quantity)
        reference_type, reference_id = self._validate_reference(
            reference_type, reference_id
        )
        created_by = self._optional_identifier(created_by, "created_by")
        audit_actor_id = self._audit_actor_id(actor_type, actor_id)
        trace_id = self._trace_id(trace_id)

        async with self._session.begin():
            return await self._stock_out(
                product_id,
                warehouse_code,
                stock_quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=created_by,
                actor_type=actor_type,
                actor_id=audit_actor_id,
                trace_id=trace_id,
            )

    async def ship_reserved(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> Inventory:
        product_id = self._validate_product_id(product_id)
        warehouse_code = self._validate_warehouse_code(warehouse_code)
        shipment_quantity = self._validate_quantity(quantity)
        reference_type, reference_id = self._validate_reference(
            reference_type, reference_id
        )
        created_by = self._optional_identifier(created_by, "created_by")
        audit_actor_id = self._audit_actor_id(actor_type, actor_id)
        trace_id = self._trace_id(trace_id)

        async with self._session.begin():
            return await self._ship_reserved(
                product_id,
                warehouse_code,
                shipment_quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=created_by,
                actor_type=actor_type,
                actor_id=audit_actor_id,
                trace_id=trace_id,
            )

    async def stock_in_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> Inventory:
        if not self._session.in_transaction():
            raise RuntimeError("stock_in_in_transaction requires an active transaction")
        product_id = self._validate_product_id(product_id)
        warehouse_code = self._validate_warehouse_code(warehouse_code)
        reference_type, reference_id = self._validate_reference(
            reference_type, reference_id
        )
        created_by = self._optional_identifier(created_by, "created_by")
        audit_actor_id = self._audit_actor_id(actor_type, actor_id)
        return await self._stock_in(
            product_id,
            warehouse_code,
            self._validate_quantity(quantity),
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
            actor_type=actor_type,
            actor_id=audit_actor_id,
            trace_id=self._trace_id(trace_id),
        )

    async def stock_out_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> Inventory:
        if not self._session.in_transaction():
            raise RuntimeError(
                "stock_out_in_transaction requires an active transaction"
            )
        product_id = self._validate_product_id(product_id)
        warehouse_code = self._validate_warehouse_code(warehouse_code)
        reference_type, reference_id = self._validate_reference(
            reference_type, reference_id
        )
        created_by = self._optional_identifier(created_by, "created_by")
        audit_actor_id = self._audit_actor_id(actor_type, actor_id)
        return await self._stock_out(
            product_id,
            warehouse_code,
            self._validate_quantity(quantity),
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
            actor_type=actor_type,
            actor_id=audit_actor_id,
            trace_id=self._trace_id(trace_id),
        )

    async def ship_reserved_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: str | None = None,
        actor_type: ActorType = ActorType.SYSTEM,
        actor_id: str | None = None,
        trace_id: str | None = None,
    ) -> Inventory:
        if not self._session.in_transaction():
            raise RuntimeError(
                "ship_reserved_in_transaction requires an active transaction"
            )
        product_id = self._validate_product_id(product_id)
        warehouse_code = self._validate_warehouse_code(warehouse_code)
        reference_type, reference_id = self._validate_reference(
            reference_type, reference_id
        )
        created_by = self._optional_identifier(created_by, "created_by")
        audit_actor_id = self._audit_actor_id(actor_type, actor_id)
        return await self._ship_reserved(
            product_id,
            warehouse_code,
            self._validate_quantity(quantity),
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
            actor_type=actor_type,
            actor_id=audit_actor_id,
            trace_id=self._trace_id(trace_id),
        )

    async def _stock_in(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal,
        *,
        reference_type: str | None,
        reference_id: int | None,
        created_by: str | None,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> Inventory:
        change = await self._balances.increase_on_hand_in_transaction(
            product_id,
            warehouse_code,
            quantity,
        )
        inventory = change.inventory
        movement = self._create_movement(
            inventory=inventory,
            movement_type=MovementType.IN,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )
        await self._movements.save(movement)
        await self._audits.append(
            self._inventory_audit_log(
                inventory,
                before_data=change.before_data,
                movement_type=MovementType.IN,
                quantity=quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                movement_created_by=created_by,
            )
        )
        return inventory

    async def _stock_out(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal,
        *,
        reference_type: str | None,
        reference_id: int | None,
        created_by: str | None,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> Inventory:
        change = await self._balances.decrease_available_in_transaction(
            product_id,
            warehouse_code,
            quantity,
        )
        inventory = change.inventory
        movement = self._create_movement(
            inventory=inventory,
            movement_type=MovementType.OUT,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )
        await self._movements.save(movement)
        await self._audits.append(
            self._inventory_audit_log(
                inventory,
                before_data=change.before_data,
                movement_type=MovementType.OUT,
                quantity=quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                movement_created_by=created_by,
            )
        )
        return inventory

    async def _ship_reserved(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal,
        *,
        reference_type: str | None,
        reference_id: int | None,
        created_by: str | None,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
    ) -> Inventory:
        change = await self._balances.ship_reserved_in_transaction(
            product_id,
            warehouse_code,
            quantity,
        )
        inventory = change.inventory
        movement = self._create_movement(
            inventory=inventory,
            movement_type=MovementType.OUT,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )
        await self._movements.save(movement)
        await self._audits.append(
            self._inventory_audit_log(
                inventory,
                before_data=change.before_data,
                movement_type=MovementType.OUT,
                quantity=quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                actor_type=actor_type,
                actor_id=actor_id,
                trace_id=trace_id,
                movement_created_by=created_by,
                action="SHIP_RESERVED",
            )
        )
        return inventory

    @staticmethod
    def _audit_actor_id(actor_type: ActorType, actor_id: str | None) -> str:
        if not isinstance(actor_type, ActorType):
            raise InvalidInventoryDataError("actor_type is invalid")
        if actor_id is not None and actor_id.strip():
            return actor_id.strip()
        if actor_type == ActorType.SYSTEM and actor_id is None:
            return "SYSTEM"
        raise InvalidInventoryDataError(
            "audit actor_id is required for this actor_type"
        )

    @staticmethod
    def _validate_product_id(product_id: object) -> int:
        return InventoryBalanceService.validate_product_id(product_id)

    @staticmethod
    def _validate_warehouse_code(warehouse_code: object) -> str:
        return InventoryBalanceService.validate_warehouse_code(warehouse_code)

    @staticmethod
    def _validate_reference(
        reference_type: object,
        reference_id: object,
    ) -> tuple[str | None, int | None]:
        if (reference_type is None) != (reference_id is None):
            raise InvalidInventoryDataError(
                "reference_type and reference_id must be provided together"
            )
        if reference_type is None:
            return None, None
        if not isinstance(reference_type, str) or not reference_type.strip():
            raise InvalidInventoryDataError("reference_type must be a nonempty string")
        normalized_type = reference_type.strip()
        if len(normalized_type) > 64:
            raise InvalidInventoryDataError("reference_type exceeds 64 characters")
        if (
            isinstance(reference_id, bool)
            or not isinstance(reference_id, int)
            or reference_id <= 0
        ):
            raise InvalidInventoryDataError("reference_id must be a positive integer")
        return normalized_type, reference_id

    @staticmethod
    def _optional_identifier(value: object, field_name: str) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str) or not value.strip():
            raise InvalidInventoryDataError(f"{field_name} must be a nonempty string")
        normalized = value.strip()
        if len(normalized) > 255:
            raise InvalidInventoryDataError(f"{field_name} exceeds 255 characters")
        return normalized

    @staticmethod
    def _trace_id(trace_id: object) -> str:
        if trace_id is None:
            return str(uuid4())
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise InvalidInventoryDataError("trace_id must be a nonempty string")
        normalized = trace_id.strip()
        if len(normalized) > 64:
            raise InvalidInventoryDataError("trace_id exceeds 64 characters")
        return normalized

    @staticmethod
    def _inventory_snapshot(inventory: Inventory) -> dict[str, str]:
        return InventoryBalanceService.snapshot(inventory)

    @classmethod
    def _inventory_audit_log(
        cls,
        inventory: Inventory,
        *,
        before_data: dict[str, str],
        movement_type: MovementType,
        quantity: Decimal,
        reference_type: str | None,
        reference_id: int | None,
        actor_type: ActorType,
        actor_id: str,
        trace_id: str,
        movement_created_by: str | None,
        action: str | None = None,
    ) -> AuditLog:
        return AuditLog(
            actor_type=actor_type,
            actor_id=actor_id,
            action=action or (
                "STOCK_IN" if movement_type == MovementType.IN else "STOCK_OUT"
            ),
            entity_type="INVENTORY",
            entity_id=f"{inventory.product_id}:{inventory.warehouse_code}",
            before_data=before_data,
            after_data=cls._inventory_snapshot(inventory),
            trace_id=trace_id,
            metadata_={
                "quantity": str(quantity),
                "reference_type": reference_type,
                "reference_id": reference_id,
                "movement_created_by": movement_created_by,
            },
        )

    @staticmethod
    def _validate_quantity(quantity: Decimal | int) -> Decimal:
        return InventoryBalanceService.validate_quantity(quantity)

    @staticmethod
    def _create_movement(
        *,
        inventory: Inventory,
        movement_type: MovementType,
        quantity: Decimal,
        reference_type: str | None,
        reference_id: int | None,
        created_by: str | None,
    ) -> StockMovement:
        return StockMovement(
            product_id=inventory.product_id,
            warehouse_code=inventory.warehouse_code,
            movement_type=movement_type,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )
