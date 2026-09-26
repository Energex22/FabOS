import sqlite3
import unittest
from contextlib import contextmanager

from fabos_core.services.auth import AuthService


class Database:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE users (
                id TEXT PRIMARY KEY,
                email TEXT,
                username TEXT,
                password_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                account_type TEXT NOT NULL DEFAULT 'customer',
                updated_at TEXT,
                last_login_at TEXT
            );
            CREATE TABLE auth_sessions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                ip_address TEXT,
                user_agent TEXT,
                revoked_at TEXT
            );
            CREATE TABLE password_reset_tokens (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT
            );
        """)

    @contextmanager
    def connect(self):
        yield self.connection


class Accounts:
    def __init__(self, database, user_id="u1"):
        self.database = database
        self.user_id = user_id

    def get_by_email(self, email):
        return self.database.connection.execute(
            "SELECT * FROM users WHERE lower(email)=lower(?)", (email,)
        ).fetchone()

    def get_by_username(self, username):
        return self.database.connection.execute(
            "SELECT * FROM users WHERE username=?", (username,)
        ).fetchone()

    def get_user(self, user_id):
        return self.database.connection.execute(
            "SELECT * FROM users WHERE id=?", (user_id,)
        ).fetchone()

    def account_summary(self, user_id):
        return {"user": self.get_user(user_id), "customer": None}


class AuthServiceTests(unittest.TestCase):
    def setUp(self):
        self.database = Database()
        self.accounts = Accounts(self.database)
        self.auth = AuthService(self.database, self.accounts)
        password_hash = self.auth.hash_password("correct horse battery staple")
        self.database.connection.execute(
            "INSERT INTO users(id,email,username,password_hash,active,account_type) "
            "VALUES('u1','customer@example.com','customer',?,1,'customer')",
            (password_hash,),
        )
        self.database.connection.commit()

    def test_password_hash_is_not_reversible_and_verifies(self):
        stored = self.database.connection.execute(
            "SELECT password_hash FROM users WHERE id='u1'"
        ).fetchone()["password_hash"]
        self.assertNotEqual(stored, "correct horse battery staple")
        self.assertTrue(self.auth.verify_password("correct horse battery staple", stored))
        self.assertFalse(self.auth.verify_password("wrong password", stored))

    def test_login_creates_session_and_logout_revokes_it(self):
        result = self.auth.login("customer@example.com", "correct horse battery staple")
        self.assertIsNotNone(result)
        token = result["token"]
        self.assertIsNotNone(self.auth.authenticate(token))
        self.assertTrue(self.auth.logout(token))
        self.assertIsNone(self.auth.authenticate(token))

    def test_login_records_client_context(self):
        result = self.auth.login(
            "customer@example.com",
            "correct horse battery staple",
            ip_address="192.0.2.10",
            user_agent="TestBrowser/1.0",
        )
        row = self.database.connection.execute(
            "SELECT ip_address,user_agent FROM auth_sessions WHERE user_id='u1'"
        ).fetchone()
        self.assertIsNotNone(result)
        self.assertEqual(row["ip_address"], "192.0.2.10")
        self.assertEqual(row["user_agent"], "TestBrowser/1.0")

    def test_password_change_revokes_existing_sessions(self):
        first = self.auth.login("customer@example.com", "correct horse battery staple")
        self.assertIsNotNone(first)
        self.auth.set_password("u1", "new secure password")
        self.assertIsNone(self.auth.authenticate(first["token"]))
        second = self.auth.login("customer@example.com", "new secure password")
        self.assertIsNotNone(second)

    def test_reset_token_is_single_use_and_revokes_sessions(self):
        session = self.auth.login("customer@example.com", "correct horse battery staple")
        reset = self.auth.request_password_reset("customer@example.com")
        self.assertIsNotNone(reset)
        self.assertTrue(self.auth.reset_password(reset["token"], "another secure password"))
        self.assertFalse(self.auth.reset_password(reset["token"], "third secure password"))
        self.assertIsNone(self.auth.authenticate(session["token"]))
        self.assertIsNotNone(
            self.auth.login("customer@example.com", "another secure password")
        )


if __name__ == "__main__":
    unittest.main()
