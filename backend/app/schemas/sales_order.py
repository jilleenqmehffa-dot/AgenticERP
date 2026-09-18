from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import SalesOrderStatus
from app.schemas.account_receivable import AccountReceivableRead
from app.schemas.sales_order_item import SalesOrderItemRead


class SalesOrderBase(BaseModel):
    order_no: str = Field(min_length=1, max_length=64)
    customer_name: str = Field(min_length=1, max_length=255)
    status: SalesOrderStatus = SalesOrderStatus.DRAFT
    total_amount: Decimal = Field(default=Decimal("0.00"), ge=0, max_digits=18, decimal_places=2)


class SalesOrderCreate(SalesOrderBase):
    pass


class SalesOrderUpdate(BaseModel):
    customer_name: str | None = Field(default=None, min_length=1, max_length=255)
    status: SalesOrderStatus | None = None
    total_amount: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=2)


class SalesOrderRead(SalesOrderBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    items: list[SalesOrderItemRead] = Field(default_factory=list)
    receivable: AccountReceivableRead | None = None
