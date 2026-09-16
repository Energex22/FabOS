import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fabos_api import FabOSAPI
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.auth import AuthService
from fabos_core.services.permissions import PermissionService
from fabos_core.services.security import SecurityService


class Pass24CustomerAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        database = Database(Path(self.temp.name) / "fabos.db")
        database.initialize()
        migrate(database)
        accounts = AccountService(database)
        permissions = PermissionService(database)
        auth = AuthService(database, accounts)
        security = SecurityService(database, auth, accounts, permissions)
        self.core = SimpleNamespace(
            database=database,
            accounts=accounts,
            permissions=permissions,
            auth=auth,
            security=security,
        )
        self.api = FabOSAPI(self.core)

    def tearDown(self):
        self.temp.cleanup()

    def test_register_and_read_customer_profile(self):
        result = self.api.request(
            "POST",
            "/api/v1/auth/register",
            {"name": "Test Customer", "email": "api@example.com", "password": "password123"},
        )
        self.assertEqual(result["status"], 201)
        token = result["data"]["token"]
        profile = self.api.request(
            "GET",
            "/api/v1/customer/me",
            headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(profile["status"], 200)
        self.assertEqual(profile["data"]["customer"]["email"], "api@example.com")
        self.assertEqual(profile["data"]["user"]["account_type"], "customer")

    def test_invalid_session_cannot_use_customer_profile_route(self):
        result = self.api.request(
            "GET", "/api/v1/customer/me", headers={"Authorization": "Bearer invalid"}
        )
        self.assertEqual(result["status"], 401)


if __name__ == "__main__":
    unittest.main()
