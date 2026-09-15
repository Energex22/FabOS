import tempfile
import unittest

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.permissions import PermissionService


class Pass15PermissionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(self.tmp.name)
        migrate(self.db)
        self.permissions = PermissionService(self.db)

    def tearDown(self):
        try:
            import os
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_role_defaults(self):
        self.assertTrue(self.permissions.has_permission("administrator", "settings.manage"))
        self.assertFalse(self.permissions.has_permission("employee", "settings.manage"))
        self.assertTrue(self.permissions.has_permission("customer", "order.read"))
        self.assertFalse(self.permissions.has_permission("customer", "order.manage"))

    def test_invalid_permission_is_rejected(self):
        with self.assertRaises(ValueError):
            self.permissions.has_permission("administrator", "not.real")

    def test_user_override_can_grant_and_revoke(self):
        with self.db.connect() as connection:
            connection.execute(
                "INSERT INTO users(id,username,password_hash,role) VALUES(?,?,?,?)",
                ("u1", "employee1", "hash", "employee"),
            )
            connection.commit()

        self.assertFalse(self.permissions.has_permission("employee", "settings.manage", user_id="u1"))
        self.permissions.set_user_permission("u1", "settings.manage", True)
        self.assertTrue(self.permissions.has_permission("employee", "settings.manage", user_id="u1"))
        self.permissions.set_user_permission("u1", "settings.manage", False)
        self.assertFalse(self.permissions.has_permission("employee", "settings.manage", user_id="u1"))
        self.permissions.clear_user_permission("u1", "settings.manage")
        self.assertFalse(self.permissions.has_permission("employee", "settings.manage", user_id="u1"))


if __name__ == "__main__":
    unittest.main()
