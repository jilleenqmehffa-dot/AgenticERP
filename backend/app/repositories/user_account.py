from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_account import UserAccount


class UserAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_username(self, username: str) -> UserAccount | None:
        return await self._session.scalar(
            select(UserAccount).where(UserAccount.username == username)
        )

    async def save(self, account: UserAccount) -> UserAccount:
        self._session.add(account)
        await self._session.flush()
        return account
