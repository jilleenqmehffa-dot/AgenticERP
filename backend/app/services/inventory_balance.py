from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    InsufficientReservedStockError,
    InsufficientStockError,
    InvalidInventoryDataError,
    InvalidStockQuantityError,
    InventoryNotFoundError,
)
from app.domain.inventory import calculate_available, evaluate_inventory_status
from app.models.inventory import Inventory
from app.repositories.inventory import InventoryRepository


@dataclass(frozen=True)
class InventoryBalanceChange:
    inventory: Inventory
    before_data: dict[str, str]


class InventoryBalanceService:
    """The single write boundary for warehouse-level inventory balances."""

    def __init__(
        self,
        session: AsyncSession,
        inventory_repository: InventoryRepository | None = None,
    ) -> None:
        self._session = session
        self._inventories = inventory_repository or InventoryRepository(session)

    async def increase_on_hand_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
    ) -> InventoryBalanceChange:
        inventory, stock_quantity = await self._locked_balance(
            product_id,
            warehouse_code,
            quantity,
        )
        before_data = self.snapshot(inventory)
        inventory.on_hand_quantity += stock_quantity
        self._refresh_status(inventory)
        await self._inventories.save(inventory)
        return InventoryBalanceChange(inventory, before_data)

    async def decrease_available_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
    ) -> InventoryBalanceChange:
        inventory, stock_quantity = await self._locked_balance(
            product_id,
            warehouse_code,
            quantity,
        )
        available_quantity = calculate_available(
            inventory.on_hand_quantity,
            inventory.reserved_quantity,
        )
        if available_quantity < stock_quantity:
            raise InsufficientStockError(available_quantity, stock_quantity)
        before_data = self.snapshot(inventory)
        inventory.on_hand_quantity -= stock_quantity
        self._refresh_status(inventory)
        await self._inventories.save(inventory)
        return InventoryBalanceChange(inventory, before_data)

    async def reserve_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
    ) -> InventoryBalanceChange:
        inventory, stock_quantity = await self._locked_balance(
            product_id,
            warehouse_code,
            quantity,
        )
        available_quantity = calculate_available(
            inventory.on_hand_quantity,
            inventory.reserved_quantity,
        )
        if available_quantity < stock_quantity:
            raise InsufficientStockError(available_quantity, stock_quantity)
        before_data = self.snapshot(inventory)
        inventory.reserved_quantity += stock_quantity
        self._refresh_status(inventory)
        await self._inventories.save(inventory)
        return InventoryBalanceChange(inventory, before_data)

    async def release_reserved_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
    ) -> InventoryBalanceChange:
        inventory, stock_quantity = await self._locked_balance(
            product_id,
            warehouse_code,
            quantity,
        )
        if inventory.reserved_quantity < stock_quantity:
            raise InsufficientReservedStockError(
                inventory.reserved_quantity,
                stock_quantity,
            )
        before_data = self.snapshot(inventory)
        inventory.reserved_quantity -= stock_quantity
        self._refresh_status(inventory)
        await self._inventories.save(inventory)
        return InventoryBalanceChange(inventory, before_data)

    async def ship_reserved_in_transaction(
        self,
        product_id: int,
        warehouse_code: str,
        quantity: Decimal | int,
    ) -> InventoryBalanceChange:
        inventory, stock_quantity = await self._locked_balance(
            product_id,
            warehouse_code,
            quantity,
        )
        if inventory.reserved_quantity < stock_quantity:
            raise InsufficientReservedStockError(
                inventory.reserved_quantity,
                stock_quantity,
            )
        before_data = self.snapshot(inventory)
        inventory.on_hand_quantity -= stock_quantity
        inventory.reserved_quantity -= stock_quantity
        self._refresh_status(inventory)
        await self._inventories.save(inventory)
        return InventoryBalanceChange(inventory, before_data)

    async def _locked_balance(
        self,
        product_id: object,
        warehouse_code: object,
        quantity: object,
    ) -> tuple[Inventory, Decimal]:
        self._require_transaction()
        normalized_product_id = self.validate_product_id(product_id)
        normalized_warehouse_code = self.validate_warehouse_code(warehouse_code)
        stock_quantity = self.validate_quantity(quantity)
        inventory = await self._inventories.get_for_update(
            normalized_product_id,
            normalized_warehouse_code,
        )
        if inventory is None:
            raise InventoryNotFoundError(
                normalized_product_id,
                normalized_warehouse_code,
            )
        return inventory, stock_quantity

    def _require_transaction(self) -> None:
        if not self._session.in_transaction():
            raise RuntimeError(
                "inventory balance mutation requires an active transaction"
            )

    @staticmethod
    def validate_product_id(product_id: object) -> int:
        if (
            isinstance(product_id, bool)
            or not isinstance(product_id, int)
            or product_id <= 0
        ):
            raise InvalidInventoryDataError("product_id must be a positive integer")
        return product_id

    @staticmethod
    def validate_warehouse_code(warehouse_code: object) -> str:
        if not isinstance(warehouse_code, str) or not warehouse_code.strip():
            raise InvalidInventoryDataError(
                "warehouse_code must be a nonempty string"
            )
        normalized = warehouse_code.strip()
        if len(normalized) > 64:
            raise InvalidInventoryDataError("warehouse_code exceeds 64 characters")
        return normalized

    @staticmethod
    def validate_quantity(quantity: object) -> Decimal:
        try:
            stock_quantity = Decimal(str(quantity))
        except (InvalidOperation, TypeError, ValueError):
            raise InvalidStockQuantityError(quantity) from None
        if not stock_quantity.is_finite() or stock_quantity <= 0:
            raise InvalidStockQuantityError(quantity)
        return stock_quantity

    @staticmethod
    def snapshot(inventory: Inventory) -> dict[str, str]:
        return {
            "on_hand_quantity": str(inventory.on_hand_quantity),
            "reserved_quantity": str(inventory.reserved_quantity),
            "status": inventory.status.value,
        }

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
