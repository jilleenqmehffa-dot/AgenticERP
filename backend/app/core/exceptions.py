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


class TaskError(Exception):
    """Base exception for controlled task operations."""


class TaskNotFoundError(TaskError, LookupError):
    def __init__(self, task_id: int) -> None:
        super().__init__(f"task not found: {task_id}")


class TaskPermissionError(TaskError, PermissionError):
    def __init__(self, task_id: int) -> None:
        super().__init__(f"employee is not assigned to task {task_id}")


class InactiveEmployeeError(TaskError):
    def __init__(self, employee_id: int) -> None:
        super().__init__(f"employee is not active: {employee_id}")


class InvalidTaskStateError(TaskError):
    def __init__(self, task_id: int) -> None:
        super().__init__(f"task is not pending: {task_id}")


class InvalidTaskDataError(TaskError, ValueError):
    pass


class UnsupportedTaskTypeError(TaskError):
    def __init__(self, task_type: object) -> None:
        super().__init__(f"unsupported task type: {task_type}")
