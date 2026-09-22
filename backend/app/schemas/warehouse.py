from pydantic import BaseModel, ConfigDict, Field


class WarehouseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)


class WarehouseRead(WarehouseCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int


class WarehouseLocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    warehouse_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=64)


class WarehouseLocationRead(WarehouseLocationCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
