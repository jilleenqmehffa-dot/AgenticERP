import unittest

from app.core.enums import InventoryStatus
from app.domain.inventory import calculate_available, evaluate_inventory_status


class CalculateAvailableTests(unittest.TestCase):
    def test_subtracts_reserved_quantity_from_on_hand_quantity(self) -> None:
        self.assertEqual(calculate_available(100, 30), 70)

    def test_returns_zero_when_all_on_hand_inventory_is_reserved(self) -> None:
        self.assertEqual(calculate_available(10, 10), 0)

    def test_preserves_negative_result_for_inconsistent_input(self) -> None:
        self.assertEqual(calculate_available(5, 8), -3)


class EvaluateInventoryStatusTests(unittest.TestCase):
    def test_returns_out_of_stock_when_available_quantity_is_zero(self) -> None:
        self.assertEqual(
            evaluate_inventory_status(0, 10),
            InventoryStatus.OUT_OF_STOCK,
        )

    def test_returns_out_of_stock_when_available_quantity_is_negative(self) -> None:
        self.assertEqual(
            evaluate_inventory_status(-1, 10),
            InventoryStatus.OUT_OF_STOCK,
        )

    def test_returns_low_stock_below_threshold(self) -> None:
        self.assertEqual(
            evaluate_inventory_status(9, 10),
            InventoryStatus.LOW_STOCK,
        )

    def test_returns_normal_at_threshold(self) -> None:
        self.assertEqual(
            evaluate_inventory_status(10, 10),
            InventoryStatus.NORMAL,
        )

    def test_returns_normal_above_threshold(self) -> None:
        self.assertEqual(
            evaluate_inventory_status(11, 10),
            InventoryStatus.NORMAL,
        )

    def test_positive_inventory_is_normal_when_threshold_is_zero(self) -> None:
        self.assertEqual(
            evaluate_inventory_status(1, 0),
            InventoryStatus.NORMAL,
        )


if __name__ == "__main__":
    unittest.main()
