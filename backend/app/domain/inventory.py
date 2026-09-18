from app.core.enums import InventoryStatus


def calculate_available(
    on_hand_quantity: int,
    reserved_quantity: int,
) -> int:
    """Calculate the inventory quantity available to new business."""
    return on_hand_quantity - reserved_quantity


def evaluate_inventory_status(
    available_quantity: int,
    low_stock_threshold: int,
) -> InventoryStatus:
    """Evaluate inventory status from the available quantity and threshold."""
    if available_quantity <= 0:
        return InventoryStatus.OUT_OF_STOCK

    if available_quantity < low_stock_threshold:
        return InventoryStatus.LOW_STOCK

    return InventoryStatus.NORMAL
