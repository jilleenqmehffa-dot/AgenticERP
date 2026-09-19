from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import MovementType
from app.core.exceptions import (
    InsufficientStockError,
    InvalidStockQuantityError,
    InventoryNotFoundError,
)
from app.domain.inventory import calculate_available, evaluate_inventory_status
from app.models.inventory import Inventory
from app.models.stock_movement import StockMovement
from app.repositories.inventory import InventoryRepository
from app.repositories.stock_movement import StockMovementRepository


class InventoryService:
    def __init__(
        self,
        session: AsyncSession,
        inventory_repository: InventoryRepository | None = None,
        movement_repository: StockMovementRepository | None = None,
    ) -> None:
        self._session = session
        self._inventories = inventory_repository or InventoryRepository(session)
        self._movements = movement_repository or StockMovementRepository(session)

    async def stock_in(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
        *,
        reference_type: str | None = None,
        reference_id: int | None = None,
        created_by: str | None = None,
    ) -> Inventory:
        stock_quantity = self._validate_quantity(quantity)

        async with self._session.begin():
            return await self._stock_in(
                product_id,
                warehouse_code,
                stock_quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=created_by,
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
    ) -> Inventory:
        stock_quantity = self._validate_quantity(quantity)

        async with self._session.begin():
            return await self._stock_out(
                product_id,
                warehouse_code,
                stock_quantity,
                reference_type=reference_type,
                reference_id=reference_id,
                created_by=created_by,
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
    ) -> Inventory:
        if not self._session.in_transaction():
            raise RuntimeError("stock_in_in_transaction requires an active transaction")
        return await self._stock_in(
            product_id,
            warehouse_code,
            self._validate_quantity(quantity),
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
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
    ) -> Inventory:
        if not self._session.in_transaction():
            raise RuntimeError(
                "stock_out_in_transaction requires an active transaction"
            )
        return await self._stock_out(
            product_id,
            warehouse_code,
            self._validate_quantity(quantity),
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
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
    ) -> Inventory:
        inventory = await self._get_locked_inventory(product_id, warehouse_code)
        inventory.on_hand_quantity += quantity
        self._refresh_status(inventory)
        movement = self._create_movement(
            inventory=inventory,
            movement_type=MovementType.IN,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )
        await self._inventories.save(inventory)
        await self._movements.save(movement)
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
    ) -> Inventory:
        inventory = await self._get_locked_inventory(product_id, warehouse_code)
        available_quantity = calculate_available(
            inventory.on_hand_quantity,
            inventory.reserved_quantity,
        )
        if available_quantity < quantity:
            raise InsufficientStockError(available_quantity, quantity)
        inventory.on_hand_quantity -= quantity
        self._refresh_status(inventory)
        movement = self._create_movement(
            inventory=inventory,
            movement_type=MovementType.OUT,
            quantity=quantity,
            reference_type=reference_type,
            reference_id=reference_id,
            created_by=created_by,
        )
        await self._inventories.save(inventory)
        await self._movements.save(movement)
        return inventory

    async def _get_locked_inventory(
        self,
        product_id: int,
        warehouse_code: str,
    ) -> Inventory:
        inventory = await self._inventories.get_for_update(
            product_id,
            warehouse_code,
        )
        if inventory is None:
            raise InventoryNotFoundError(product_id, warehouse_code)
        return inventory

    @staticmethod
    def _validate_quantity(quantity: Decimal | int) -> Decimal:
        try:
            stock_quantity = Decimal(str(quantity))
        except (InvalidOperation, TypeError, ValueError):
            raise InvalidStockQuantityError(quantity) from None

        if not stock_quantity.is_finite() or stock_quantity <= 0:
            raise InvalidStockQuantityError(quantity)
        return stock_quantity

    @staticmethod
    def _refresh_status(inventory: Inventory) -> None:
        available_quantity = calculate_available(
            inventory.on_hand_quantity,
            inventory.reserved_quantity,
        )
        inventory.status = evaluate_inventory_status(
            available_quantity,
            inventory.low_stock_threshold,
        )

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
