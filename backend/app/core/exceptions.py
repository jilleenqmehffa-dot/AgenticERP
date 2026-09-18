from decimal import Decimal


class InventoryError(Exception):
    """Base exception for controlled inventory operations."""


class InvalidStockQuantityError(InventoryError, ValueError):
    def __init__(self, quantity: object) -> None:
        super().__init__(f"stock quantity must be greater than zero: {quantity!r}")


class InventoryNotFoundError(InventoryError, LookupError):
    def __init__(self, product_id: int, warehouse_code: str) -> None:
        super().__init__(
            f"inventory not found for product {product_id} "
            f"in warehouse {warehouse_code!r}"
        )


class InsufficientStockError(InventoryError):
    def __init__(self, available_quantity: Decimal, requested_quantity: Decimal) -> None:
        self.available_quantity = available_quantity
        self.requested_quantity = requested_quantity
        super().__init__(
            "insufficient available stock: "
            f"available={available_quantity}, requested={requested_quantity}"
        )
