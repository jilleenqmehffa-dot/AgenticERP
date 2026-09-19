from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.core.enums import EmployeeStatus
from app.schemas.role import RoleRead


class EmployeeBase(BaseModel):
    employee_no: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    role_id: int = Field(gt=0)
    department: str = Field(min_length=1, max_length=100)
    status: EmployeeStatus = EmployeeStatus.ACTIVE


class EmployeeCreate(EmployeeBase):
    pass


class EmployeeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    role_id: int | None = Field(default=None, gt=0)
    department: str | None = Field(default=None, min_length=1, max_length=100)
    status: EmployeeStatus | None = None


class EmployeeRead(EmployeeBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    updated_at: datetime
    role: RoleRead
