import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import InvalidCredentialsError
from app.core.passwords import hash_password, verify_password
from app.models.user_account import UserAccount
from app.repositories.user_account import UserAccountRepository
from app.services.auth.account import AuthenticatedSession, authenticate_account


class FakeTransaction:
    def __init__(self) -> None:
        self.exception_type: type[BaseException] | None = None

    async def __aenter__(self) -> "FakeTransaction":
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        self.exception_type = exception_type
        return False


class FakeSession:
    def __init__(self) -> None:
        self.transaction = FakeTransaction()
        self.begin_calls = 0

    def begin(self) -> FakeTransaction:
        self.begin_calls += 1
        return self.transaction


class PasswordHashTests(unittest.TestCase):
    def test_hash_is_salted_and_verifies_only_the_matching_password(self) -> None:
        first = hash_password("correct horse battery staple")
        second = hash_password("correct horse battery staple")

        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("correct horse battery staple", first))
        self.assertFalse(verify_password("wrong password", first))
        self.assertNotIn("correct horse battery staple", first)

    def test_malformed_or_excessive_hash_cost_fails_closed(self) -> None:
        self.assertFalse(verify_password("password", "plain-text"))
        self.assertFalse(
            verify_password("password", "pbkdf2_sha256$999999999$00$00")
        )
        self.assertFalse(verify_password("password", "pbkdf2_sha256$600000$zz$zz"))


class UserAccountRepositoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_by_username_queries_one_account(self) -> None:
        session = MagicMock()
        session.scalar = AsyncMock(return_value=None)

        result = await UserAccountRepository(session).get_by_username("operator1")

        self.assertIsNone(result)
        statement = session.scalar.await_args.args[0]
        self.assertEqual(statement.compile().params, {"username_1": "operator1"})
        self.assertEqual(statement.column_descriptions[0]["entity"], UserAccount)


class AccountAuthenticationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.session = FakeSession()
        self.repository = MagicMock()
        self.account = UserAccount(
            id=9,
            employee_id=23,
            username="operator1",
            password_hash=hash_password("valid-password"),
            is_active=True,
        )
        self.repository.get_by_username = AsyncMock(return_value=self.account)
        self.repository.save = AsyncMock(side_effect=lambda account: account)
        self.audits = MagicMock()
        self.audits.append = AsyncMock(side_effect=lambda audit: audit)

    async def test_valid_account_returns_employee_session(self) -> None:
        result = await authenticate_account(
            self.session, "operator1", "valid-password", self.repository, self.audits
        )

        self.assertIsInstance(result, AuthenticatedSession)
        self.assertEqual(result.account_id, 9)
        self.assertEqual(result.employee_id, 23)
        self.assertEqual(result.username, "operator1")
        self.assertIsNotNone(result.authenticated_at.tzinfo)
        self.repository.get_by_username.assert_awaited_once_with("operator1")
        self.assertIsNotNone(self.account.last_login_at)
        self.repository.save.assert_awaited_once_with(self.account)
        audit = self.audits.append.await_args.args[0]
        self.assertEqual(audit.action, "AUTHENTICATION_SUCCEEDED")
        self.assertEqual(audit.actor_id, "23")
        self.assertEqual(audit.after_data, {"authenticated": True})
        self.assertNotIn("password", audit.metadata_)
        self.assertEqual(self.session.begin_calls, 1)

    async def test_unknown_wrong_password_and_inactive_account_share_error(self) -> None:
        messages = []
        self.repository.get_by_username.return_value = None
        with self.assertRaises(InvalidCredentialsError) as raised:
            await authenticate_account(
                self.session,
                "missing",
                "valid-password",
                self.repository,
                self.audits,
            )
        messages.append(str(raised.exception))

        self.repository.get_by_username.return_value = self.account
        with self.assertRaises(InvalidCredentialsError) as raised:
            await authenticate_account(
                self.session,
                "operator1",
                "wrong-password",
                self.repository,
                self.audits,
            )
        messages.append(str(raised.exception))

        self.account.is_active = False
        with self.assertRaises(InvalidCredentialsError) as raised:
            await authenticate_account(
                self.session,
                "operator1",
                "valid-password",
                self.repository,
                self.audits,
            )
        messages.append(str(raised.exception))

        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn("valid-password", messages[0])
        self.assertEqual(self.audits.append.await_count, 3)
        for call in self.audits.append.await_args_list:
            audit = call.args[0]
            self.assertEqual(audit.action, "AUTHENTICATION_FAILED")
            self.assertEqual(audit.after_data, {"authenticated": False})
            self.assertNotIn("password", audit.metadata_)
        self.repository.save.assert_not_awaited()

    async def test_malformed_stored_hash_is_rejected(self) -> None:
        self.account.password_hash = "not-a-valid-hash"

        with self.assertRaises(InvalidCredentialsError):
            await authenticate_account(
                self.session,
                "operator1",
                "valid-password",
                self.repository,
                self.audits,
            )

        self.audits.append.assert_awaited_once()

    async def test_audit_failure_aborts_authentication_transaction(self) -> None:
        self.audits.append.side_effect = RuntimeError("audit unavailable")

        with self.assertRaisesRegex(RuntimeError, "audit unavailable"):
            await authenticate_account(
                self.session,
                "operator1",
                "valid-password",
                self.repository,
                self.audits,
            )

        self.assertIs(self.session.transaction.exception_type, RuntimeError)


if __name__ == "__main__":
    unittest.main()
