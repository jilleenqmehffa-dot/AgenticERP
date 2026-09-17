from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SalesOrderItemBase(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class SalesOrderItemCreate(SalesOrderItemBase):
    sales_order_id: int = Field(gt=0)


class SalesOrderItemUpdate(BaseModel):
    product_id: int | None = Field(default=None, gt=0)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)


class SalesOrderItemRead(SalesOrderItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sales_order_id: int

