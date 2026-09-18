from datetime import date, datetime
from decimal import Decimal
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.enums import ReceivableStatus


class AccountReceivableBase(BaseModel):
    customer_name: str = Field(min_length=1, max_length=255)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    paid_amount: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    due_date: date
    status: ReceivableStatus = ReceivableStatus.UNPAID

    @model_validator(mode="after")
    def validate_paid_amount(self) -> Self:
        if self.paid_amount > self.amount:
            raise ValueError("paid_amount cannot exceed amount")
        return self


class AccountReceivableCreate(AccountReceivableBase):
    sales_order_id: int = Field(gt=0)


class AccountReceivableUpdate(BaseModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=255)
    amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    paid_amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=18,
        decimal_places=2,
    )
    due_date: date | None = None
    status: ReceivableStatus | None = None


class AccountReceivableRead(AccountReceivableBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sales_order_id: int
    outstanding_amount: Decimal
    created_at: datetime
    updated_at: datetime
