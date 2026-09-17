from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import ProductStatus


class ProductBase(BaseModel):
    sku: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    category: str = Field(min_length=1, max_length=100)
    unit: str = Field(min_length=1, max_length=32)
    status: ProductStatus = ProductStatus.ACTIVE


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    sku: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    unit: str | None = Field(default=None, min_length=1, max_length=32)
    status: ProductStatus | None = None


class ProductRead(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime

