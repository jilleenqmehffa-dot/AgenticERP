from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import OrderItemStatus
from app.schemas.product import ProductRead


class SalesOrderItemBase(BaseModel):
    product_id: int = Field(gt=0)
    quantity: Decimal = Field(gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    amount: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    status: OrderItemStatus = OrderItemStatus.PENDING
    reserved_quantity: Decimal = Field(
        default=Decimal("0.000"), ge=0, max_digits=18, decimal_places=3
    )
    picked_quantity: Decimal = Field(
        default=Decimal("0.000"), ge=0, max_digits=18, decimal_places=3
    )
    shipped_quantity: Decimal = Field(
        default=Decimal("0.000"), ge=0, max_digits=18, decimal_places=3
    )


class SalesOrderItemCreate(SalesOrderItemBase):
    sales_order_id: int = Field(gt=0)


class SalesOrderItemUpdate(BaseModel):
    product_id: int | None = Field(default=None, gt=0)
    quantity: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=3)
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)
    status: OrderItemStatus | None = None
    reserved_quantity: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=3
    )
    picked_quantity: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=3
    )
    shipped_quantity: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=3
    )


class SalesOrderItemRead(SalesOrderItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    sales_order_id: int
    product: ProductRead
