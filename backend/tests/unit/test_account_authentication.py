import unittest
from unittest.mock import AsyncMock, MagicMock

from app.core.exceptions import InvalidCredentialsError
from app.core.passwords import hash_password, verify_password
from app.models.user_account import UserAccount
from app.repositories.user_account import UserAccountRepository
from app.services.account import AuthenticatedSession, authenticate_account


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
        self.session = MagicMock()
        self.repository = MagicMock()
        self.account = UserAccount(
            id=9,
            employee_id=23,
            username="operator1",
            password_hash=hash_password("valid-password"),
            is_active=True,
        )
        self.repository.get_by_username = AsyncMock(return_value=self.account)

    async def test_valid_account_returns_employee_session(self) -> None:
        result = await authenticate_account(
            self.session, "operator1", "valid-password", self.repository
        )

        self.assertIsInstance(result, AuthenticatedSession)
        self.assertEqual(result.account_id, 9)
        self.assertEqual(result.employee_id, 23)
        self.assertEqual(result.username, "operator1")
        self.assertIsNotNone(result.authenticated_at.tzinfo)
        self.repository.get_by_username.assert_awaited_once_with("operator1")
        self.session.commit.assert_not_called()

    async def test_unknown_wrong_password_and_inactive_account_share_error(self) -> None:
        messages = []
        self.repository.get_by_username.return_value = None
        with self.assertRaises(InvalidCredentialsError) as raised:
            await authenticate_account(
                self.session, "missing", "valid-password", self.repository
            )
        messages.append(str(raised.exception))

        self.repository.get_by_username.return_value = self.account
        with self.assertRaises(InvalidCredentialsError) as raised:
            await authenticate_account(
                self.session, "operator1", "wrong-password", self.repository
            )
        messages.append(str(raised.exception))

        self.account.is_active = False
        with self.assertRaises(InvalidCredentialsError) as raised:
            await authenticate_account(
                self.session, "operator1", "valid-password", self.repository
            )
        messages.append(str(raised.exception))

        self.assertEqual(len(set(messages)), 1)
        self.assertNotIn("valid-password", messages[0])

    async def test_malformed_stored_hash_is_rejected(self) -> None:
        self.account.password_hash = "not-a-valid-hash"

        with self.assertRaises(InvalidCredentialsError):
            await authenticate_account(
                self.session, "operator1", "valid-password", self.repository
            )


if __name__ == "__main__":
    unittest.main()
