from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import ActorType
from app.core.exceptions import InvalidCredentialsError
from app.core.passwords import verify_password
from app.models.audit_log import AuditLog
from app.models.user_account import UserAccount
from app.repositories.audit_log import AuditLogRepository
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


class AccountService:
    def __init__(
        self,
        session: AsyncSession,
        account_repository: UserAccountRepository | None = None,
        audit_repository: AuditLogRepository | None = None,
    ) -> None:
        self._session = session
        self._accounts = account_repository or UserAccountRepository(session)
        self._audits = audit_repository or AuditLogRepository(session)

    async def authenticate(self, username: str, password: str) -> AuthenticatedSession:
        normalized_username = self._normalize_username(username)
        password_value = password if isinstance(password, str) else ""
        trace_id = str(uuid4())
        authenticated: AuthenticatedSession | None = None

        async with self._session.begin():
            account = (
                await self._accounts.get_by_username(normalized_username)
                if normalized_username
                else None
            )
            stored_hash = (
                account.password_hash if account is not None else _DUMMY_PASSWORD_HASH
            )
            password_valid = verify_password(password_value, stored_hash)

            if account is not None and password_valid and account.is_active:
                authenticated_at = datetime.now(timezone.utc)
                account.last_login_at = authenticated_at
                await self._accounts.save(account)
                authenticated = AuthenticatedSession(
                    account_id=account.id,
                    employee_id=account.employee_id,
                    username=account.username,
                    authenticated_at=authenticated_at,
                )
                await self._audits.append(
                    self._authentication_audit(
                        account=account,
                        username=normalized_username,
                        succeeded=True,
                        trace_id=trace_id,
                    )
                )
            else:
                await self._audits.append(
                    self._authentication_audit(
                        account=account,
                        username=normalized_username,
                        succeeded=False,
                        trace_id=trace_id,
                    )
                )

        if authenticated is None:
            raise InvalidCredentialsError()
        return authenticated

    @staticmethod
    def _normalize_username(value: object) -> str:
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _authentication_audit(
        *,
        account: UserAccount | None,
        username: str,
        succeeded: bool,
        trace_id: str,
    ) -> AuditLog:
        return AuditLog(
            actor_type=ActorType.EMPLOYEE if succeeded else ActorType.SYSTEM,
            actor_id=str(account.employee_id) if succeeded and account else "SYSTEM",
            action=(
                "AUTHENTICATION_SUCCEEDED"
                if succeeded
                else "AUTHENTICATION_FAILED"
            ),
            entity_type="USER_ACCOUNT",
            entity_id=str(account.id) if account is not None else "UNKNOWN",
            before_data=None,
            after_data={"authenticated": succeeded},
            trace_id=trace_id,
            metadata_={"username": username},
        )


async def authenticate_account(
    session: AsyncSession,
    username: str,
    password: str,
    repository: UserAccountRepository | None = None,
    audit_repository: AuditLogRepository | None = None,
) -> AuthenticatedSession:
    """Compatibility entry point backed by the transaction-safe account service."""
    return await AccountService(
        session,
        account_repository=repository,
        audit_repository=audit_repository,
    ).authenticate(username, password)
