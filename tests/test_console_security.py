import os
import tempfile
import unittest
from unittest import mock
from unittest import mock

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.auth import AuthService
from fabos_core.services.console_security import ConsoleSecurityService
from fabos_core.services.shop_settings import ShopSettingsService


class ConsoleSecurityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(self.tmp.name)
        self.db.initialize()
        migrate(self.db)
        self.accounts = AccountService(self.db)
        self.auth = AuthService(self.db, self.accounts)
        self.settings = ShopSettingsService(self.db)
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO users(id,username,password_hash,email,account_type,role) VALUES(?,?,?,?,?,?)",
                ("owner", "owner", "legacy", "owner@example.com", "administrator", "owner"),
            )
            connection.execute(
                "INSERT INTO users(id,username,password_hash,email,account_type,role) VALUES(?,?,?,?,?,?)",
                ("admin", "admin", "legacy", "admin@example.com", "administrator", "administrator"),
            )
            connection.commit()
        self.auth.set_password("owner", "owner-password")
        self.auth.set_password("admin", "admin-password")
        self.security = ConsoleSecurityService(self.auth, self.accounts, self.settings)

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_only_owner_can_authenticate_console(self):
        self.assertIsNotNone(self.security.authenticate_owner("owner", "owner-password"))
        self.assertIsNone(self.security.authenticate_owner("admin", "admin-password"))

    def test_inactive_owner_cannot_authenticate(self):
        with self.db.connect() as connection:
            connection.execute("UPDATE users SET active=0 WHERE id=?", ("owner",))
            connection.commit()
        self.assertIsNone(self.security.authenticate_owner("owner", "owner-password"))

    def test_ssh_session_is_rejected_when_local_only(self):
        with mock.patch.dict(os.environ, {"SSH_CONNECTION": "10.0.0.2 22 10.0.0.3 54321"}, clear=False):
            self.assertFalse(self.security.is_local_session())
            self.assertIsNone(self.security.authenticate_owner("owner", "owner-password"))

    def test_failed_logins_trigger_temporary_lockout(self):
        for _ in range(self.security.MAX_FAILED_ATTEMPTS):
            self.assertIsNone(self.security.authenticate_owner("owner", "wrong-password"))
        self.assertIsNone(self.security.authenticate_owner("owner", "owner-password"))
        lockout_expiry = self.security._locked_until
        with mock.patch("fabos_core.services.console_security.time.monotonic", return_value=lockout_expiry + 1):
            self.assertIsNotNone(self.security.authenticate_owner("owner", "owner-password"))

    def test_password_change_revokes_existing_sessions(self):
        first = self.auth.login("owner", "owner-password")
        self.assertIsNotNone(first)
        self.assertIsNotNone(self.auth.authenticate(first["token"]))

        self.auth.set_password("owner", "owner-password-2")

        self.assertIsNone(self.auth.authenticate(first["token"]))
        second = self.auth.login("owner", "owner-password-2")
        self.assertIsNotNone(second)
        self.assertNotEqual(first["token"], second["token"])

    def test_console_timeout_is_configurable(self):
        self.assertTrue(self.security.lock_enabled())
        self.assertEqual(self.security.idle_timeout_minutes(), 15)
        self.settings.set_validated("console_idle_timeout_minutes", "30")
        self.assertEqual(self.security.idle_timeout_minutes(), 30)


if __name__ == "__main__":
    unittest.main()
