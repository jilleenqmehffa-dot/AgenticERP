from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StockTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    actual_quantity: int = Field(gt=0)
    remark: str | None = Field(default=None, min_length=1, max_length=2000)


class PackTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    remark: str | None = Field(default=None, min_length=1, max_length=2000)


class MovementTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actual_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    remark: str | None = Field(default=None, min_length=1, max_length=2000)


class InventoryCountResultInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    inventory_count_item_id: int = Field(gt=0)
    counted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)


class InventoryCountTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[InventoryCountResultInput] = Field(min_length=1)
    remark: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_unique_items(self) -> "InventoryCountTaskInput":
        item_ids = [result.inventory_count_item_id for result in self.results]
        if len(item_ids) != len(set(item_ids)):
            raise ValueError("inventory count item ids must be unique")
        return self


class ReceiveTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    received_quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    accepted_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    defective_quantity: Decimal = Field(ge=0, max_digits=18, decimal_places=3)
    quarantined_quantity: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=18, decimal_places=3
    )
    rejected_quantity: Decimal = Field(
        default=Decimal("0"), ge=0, max_digits=18, decimal_places=3
    )
    lot_no: str = Field(default="", max_length=100)
    remark: str | None = Field(default=None, min_length=1, max_length=2000)

    @model_validator(mode="after")
    def validate_quality_total(self) -> "ReceiveTaskInput":
        quality_total = (
            self.accepted_quantity
            + self.defective_quantity
            + self.quarantined_quantity
            + self.rejected_quantity
        )
        if quality_total != self.received_quantity:
            raise ValueError("quality quantities must equal received_quantity")
        return self
