from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidCredentialsError
from app.core.passwords import verify_password
from app.repositories.user_account import UserAccountRepository


_DUMMY_PASSWORD_HASH = (
    "pbkdf2_sha256$600000$00000000000000000000000000000000$"
    "27d590f22594d484bddcdac07def0271f080e218ac789e9f0285cc7b4ed10d68"
)


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Internal authenticated identity; no persistent token is issued here."""

    account_id: int
    employee_id: int
    username: str
    authenticated_at: datetime


async def authenticate_account(
    session: AsyncSession,
    username: str,
    password: str,
    repository: UserAccountRepository | None = None,
) -> AuthenticatedSession:
    """Verify an account and return its employee identity for service use."""
    accounts = repository if repository is not None else UserAccountRepository(session)
    account = await accounts.get_by_username(username) if username else None
    stored_hash = account.password_hash if account is not None else _DUMMY_PASSWORD_HASH
    password_valid = verify_password(password, stored_hash)

    if account is None or not password_valid or not account.is_active:
        raise InvalidCredentialsError()

    return AuthenticatedSession(
        account_id=account.id,
        employee_id=account.employee_id,
        username=account.username,
        authenticated_at=datetime.now(timezone.utc),
    )
