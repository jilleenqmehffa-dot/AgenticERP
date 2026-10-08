from decimal import Decimal


class InventoryError(Exception):
    """Base exception for controlled inventory operations."""


class InvalidInventoryDataError(InventoryError, ValueError):
    pass


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


class InsufficientReservedStockError(InventoryError):
    def __init__(self, reserved_quantity: Decimal, requested_quantity: Decimal) -> None:
        self.reserved_quantity = reserved_quantity
        self.requested_quantity = requested_quantity
        super().__init__(
            "insufficient reserved stock: "
            f"reserved={reserved_quantity}, requested={requested_quantity}"
        )


class InvalidInventoryBucketDataError(InventoryError, ValueError):
    pass


class InventoryBucketNotFoundError(InventoryError, LookupError):
    def __init__(
        self,
        product_id: int,
        warehouse_code: str,
        location_code: str,
        lot_no: str,
        stock_status: object,
    ) -> None:
        super().__init__(
            "inventory bucket not found: "
            f"product={product_id}, warehouse={warehouse_code!r}, "
            f"location={location_code!r}, lot={lot_no!r}, "
            f"status={stock_status}"
        )


class InsufficientBucketStockError(InventoryError):
    def __init__(self, bucket_quantity: Decimal, requested_quantity: Decimal) -> None:
        self.bucket_quantity = bucket_quantity
        self.requested_quantity = requested_quantity
        super().__init__(
            "insufficient inventory bucket stock: "
            f"bucket={bucket_quantity}, requested={requested_quantity}"
        )


class ReservationError(InventoryError):
    """Base exception for controlled stock reservation operations."""


class InvalidReservationDataError(ReservationError, ValueError):
    pass


class ReservationNotFoundError(ReservationError, LookupError):
    def __init__(self, reservation_id: int) -> None:
        super().__init__(f"stock reservation not found: {reservation_id}")


class OutboundOrderItemNotFoundError(ReservationError, LookupError):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"outbound order item not found: {item_id}")


class InvalidReservationStateError(ReservationError):
    def __init__(self, reservation_id: int) -> None:
        super().__init__(
            f"stock reservation state does not allow this operation: {reservation_id}"
        )


class PackingError(Exception):
    """Base exception for controlled packing operations."""


class InvalidPackingDataError(PackingError, ValueError):
    pass


class PickingError(Exception):
    """Base exception for controlled picking operations."""


class InvalidPickingDataError(PickingError, ValueError):
    pass


class InvalidPickingStateError(PickingError):
    def __init__(self, reservation_id: int) -> None:
        super().__init__(
            f"stock reservation state does not allow picking: {reservation_id}"
        )


class ReceivingError(Exception):
    """Base exception for controlled receiving operations."""


class InvalidReceivingDataError(ReceivingError, ValueError):
    pass


class InboundReceiptItemNotFoundError(ReceivingError, LookupError):
    def __init__(self, item_id: int) -> None:
        super().__init__(f"inbound receipt item not found: {item_id}")


class InvalidReceivingStateError(ReceivingError):
    def __init__(self, receipt_id: int) -> None:
        super().__init__(
            f"inbound receipt state does not allow receiving: {receipt_id}"
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
        super().__init__(f"task state does not allow this operation: {task_id}")


class InvalidTaskDataError(TaskError, ValueError):
    pass


class UnsupportedTaskTypeError(TaskError):
    def __init__(self, task_type: object) -> None:
        super().__init__(f"unsupported task type: {task_type}")


class TaskSubmissionNotFoundError(TaskError, LookupError):
    def __init__(self, task_id: int) -> None:
        super().__init__(f"pending submission not found for task: {task_id}")


class TaskReviewPermissionError(TaskError, PermissionError):
    def __init__(self, employee_id: int) -> None:
        super().__init__(f"employee is not allowed to review tasks: {employee_id}")


class TaskExecutionNotFoundError(TaskError, LookupError):
    def __init__(self, execution_id: int) -> None:
        super().__init__(f"task execution not found: {execution_id}")


class InvalidTaskExecutionStateError(TaskError):
    def __init__(self, execution_id: int) -> None:
        super().__init__(f"task execution state does not allow this operation: {execution_id}")


class TaskExecutionAlreadyRunningError(TaskError):
    def __init__(self, execution_id: int) -> None:
        super().__init__(f"task execution is already running: {execution_id}")


class InvalidCredentialsError(PermissionError):
    def __init__(self) -> None:
        super().__init__("invalid account credentials")


class RecommendationNotFoundError(LookupError):
    def __init__(self, recommendation_id: int) -> None:
        super().__init__(f"recommendation not found: {recommendation_id}")


class InvalidRecommendationStateError(ValueError):
    pass


class RecommendationReviewPermissionError(PermissionError):
    pass
