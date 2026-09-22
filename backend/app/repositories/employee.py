from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.employee import Employee


class EmployeeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_for_update(self, employee_id: int) -> Employee | None:
        return await self._session.scalar(
            select(Employee).where(Employee.id == employee_id).with_for_update()
        )

    async def get_with_role_for_update(self, employee_id: int) -> Employee | None:
        return await self._session.scalar(
            select(Employee)
            .where(Employee.id == employee_id)
            .options(selectinload(Employee.role))
            .with_for_update()
        )
