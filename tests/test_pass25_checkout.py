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


class Pass25CheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        db = Database(Path(self.temp.name) / "fabos.db")
        db.initialize()
        migrate(db)
        self.accounts = AccountService(db)
        self.permissions = PermissionService(db)
        self.auth = AuthService(db, self.accounts)
        self.security = SecurityService(db, self.auth, self.accounts, self.permissions)
        self.core = SimpleNamespace(
            database=db,
            accounts=self.accounts,
            permissions=self.permissions,
            auth=self.auth,
            security=self.security,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_checkout_route_requires_customer(self):
        api = FabOSAPI(self.core)
        result = api.request("POST", "/api/v1/checkout/order", {"items": []}, {})
        self.assertEqual(result["status"], 401)


if __name__ == "__main__":
    unittest.main()
