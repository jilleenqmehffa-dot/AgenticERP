"""Backward-compatible import for the renamed inventory movement service."""

from app.services.inventory_movement import InventoryMovementService

# Deprecated: use InventoryMovementService for new code.
InventoryService = InventoryMovementService

__all__ = ["InventoryMovementService", "InventoryService"]
