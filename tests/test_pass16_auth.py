import tempfile
import unittest

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.auth import AuthService


class Pass16AuthTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(self.tmp.name)
        migrate(self.db)
        self.accounts = AccountService(self.db)
        self.auth = AuthService(self.db, self.accounts)
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO users(id,username,password_hash,email,account_type,role) VALUES(?,?,?,?,?,?)",
                ("u1", "admin1", "legacy-placeholder", "admin@example.com", "administrator", "owner"),
            )
            connection.commit()
        self.auth.set_password("u1", "correct-password")

    def tearDown(self):
        import os
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_password_hash_is_verifiable(self):
        stored = self.accounts.get_user("u1")["password_hash"]
        self.assertTrue(self.auth.verify_password("correct-password", stored))
        self.assertFalse(self.auth.verify_password("wrong-password", stored))

    def test_login_authenticate_and_logout(self):
        result = self.auth.login("admin1", "correct-password")
        self.assertIsNotNone(result)
        self.assertEqual(result["user"]["user"]["id"], "u1")
        self.assertIsNotNone(self.auth.authenticate(result["token"]))
        self.assertTrue(self.auth.logout(result["token"]))
        self.assertIsNone(self.auth.authenticate(result["token"]))

    def test_email_login_and_last_login(self):
        result = self.auth.login("admin@example.com", "correct-password")
        self.assertIsNotNone(result)
        self.assertIsNotNone(self.accounts.get_user("u1")["last_login_at"])

    def test_password_reset_revokes_sessions(self):
        session = self.auth.login("admin1", "correct-password")
        reset = self.auth.request_password_reset("admin@example.com")
        self.assertIsNotNone(reset)
        self.assertTrue(self.auth.reset_password(reset["token"], "new-password"))
        self.assertIsNone(self.auth.authenticate(session["token"]))
        new_session = self.auth.login("admin1", "new-password")
        self.assertIsNotNone(new_session)


if __name__ == "__main__":
    unittest.main()
