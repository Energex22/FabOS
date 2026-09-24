import os
import tempfile
import unittest

from fabos_core.application import FabOSApplication
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.auth import AuthService


class OwnerBootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(self.tmp.name)
        self.db.initialize()
        migrate(self.db)
        self.accounts = AccountService(self.db)
        self.auth = AuthService(self.db, self.accounts)
        self.app = FabOSApplication.__new__(FabOSApplication)
        self.app.database = self.db
        self.app.accounts = self.accounts
        self.app.auth = self.auth

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def _add_user(self, user_id, username, role="admin", account_type="administrator"):
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) "
                "VALUES(?,?,?,?,?,?)",
                (user_id, username, self.auth.hash_password("password"), role, 1, account_type),
            )
            connection.commit()

    def test_sole_legacy_admin_is_promoted_without_password_change(self):
        self._add_user("u1", "legacy-admin", role="admin")
        self.app._ensure_owner_account()

        user = self.accounts.get_user("u1")
        self.assertEqual(user["role"], "owner")
        self.assertEqual(user["account_type"], "administrator")
        self.assertTrue(self.auth.login("legacy-admin", "password"))

    def test_multiple_admins_are_not_guessed(self):
        self._add_user("u1", "admin-one")
        self._add_user("u2", "admin-two")
        self.app._ensure_owner_account()

        with self.db.connect() as connection:
            owners = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role='owner' AND active=1"
            ).fetchone()[0]
        self.assertEqual(owners, 0)

    def test_fresh_install_gets_owner_bootstrap(self):
        self.app._ensure_owner_account()
        owner = self.accounts.get_by_username("owner")
        self.assertIsNotNone(owner)
        self.assertEqual(owner["role"], "owner")
        self.assertEqual(owner["account_type"], "administrator")
        self.assertTrue(self.auth.login("owner", "owner-password"))




class OwnerSetupCommandTests(OwnerBootstrapTests):
    def test_owner_setup_command_changes_default_credentials(self):
        import builtins
        import getpass
        from unittest.mock import patch
        from fabos_core.cli import main

        app = self.app
        app._ensure_owner_account()
        with patch.object(builtins, "input", return_value="fabvex-admin"), patch.object(
            getpass, "getpass", side_effect=["a-strong-owner-password", "a-strong-owner-password"]
        ), patch("sys.argv", ["fabos", "setup-owner"]), patch(
            "fabos_core.cli.FabOSApplication", return_value=app
        ):
            main()
        user = app.auth.accounts.get_by_username("fabvex-admin")
        self.assertIsNotNone(user)
        self.assertIsNone(app.auth.accounts.get_by_username("owner"))
        self.assertIsNotNone(app.auth.login("fabvex-admin", "a-strong-owner-password"))
        self.assertIsNone(app.auth.login("fabvex-admin", "owner-password"))


if __name__ == "__main__":
    unittest.main()
