"""WSGI error-mapping parity for the fulfillment read endpoints (staff journey 4).

FastAPI serves GET /api/v1/fulfillments and GET /api/v1/fulfillments/{id}
(permission_user("fulfillment.read")); the admin console's Fulfillment
workspace calls both. The WSGI route existed in fabos_api/app.py but the
detail route let service errors escape: unknown ids 500'd (FastAPI: 404)
and cross-customer reads 403'd (FastAPI maps the service PermissionError
to 400). These tests pin the FastAPI-matching behavior.
"""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.permissions import PermissionService


class _Accounts:
    def get_user(self, user_id):
        account_type = {"admin-u": "administrator", "cust-u": "customer",
                        "other-u": "customer"}[user_id]
        return {"id": user_id, "active": 1, "account_type": account_type}

    def customer_for_user(self, user_id):
        return {"cust-u": {"id": "cust-1"}, "other-u": {"id": "cust-2"}}.get(user_id)


class FulfillmentReadMirrorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "fabos.sqlite3")
        self.db.initialize()
        migrate(self.db)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                ("cust-1", "Test Customer", "t@example.com"))
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("o-1", "O-1", "cust-1", "ready", 5000))
            conn.execute(
                "INSERT INTO fulfillments(id,order_id,method,status,carrier,tracking_number) VALUES(?,?,?,?,?,?)",
                ("f-1", "o-1", "shipping", "pending", "UPS", "1Z999"))
            conn.commit()
        accounts = _Accounts()
        permissions = PermissionService(self.db)
        core = SimpleNamespace(
            fulfillment=FulfillmentService(self.db, accounts=accounts, permissions=permissions),
            permissions=permissions,
            security=SimpleNamespace(context=self._context),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        self.api = FabOSAPI(core)

    def _context(self, token, permission=None):
        user_id = {"admin-token": "admin-u", "cust-token": "cust-u",
                   "other-token": "other-u"}.get(token)
        if not user_id:
            raise PermissionError("Invalid or expired session")
        return {"id": user_id,
                "account_type": _Accounts().get_user(user_id)["account_type"]}

    def _headers(self, token):
        return {"Authorization": "Bearer " + token}

    def test_admin_lists_fulfillments(self):
        result = self.api.request("GET", "/api/v1/fulfillments", {},
                                  self._headers("admin-token"))
        self.assertEqual(result["status"], 200)
        rows = result["data"]["fulfillments"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "f-1")
        self.assertEqual(rows[0]["tracking_number"], "1Z999")

    def test_admin_reads_fulfillment_detail(self):
        result = self.api.request("GET", "/api/v1/fulfillments/f-1", {},
                                  self._headers("admin-token"))
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["fulfillment"]["id"], "f-1")
        self.assertEqual(result["data"]["fulfillment"]["status"], "pending")

    def test_unknown_fulfillment_is_404(self):
        result = self.api.request("GET", "/api/v1/fulfillments/nope", {},
                                  self._headers("admin-token"))
        self.assertEqual(result["status"], 404)

    def test_unauthenticated_is_401(self):
        result = self.api.request("GET", "/api/v1/fulfillments", {}, {})
        self.assertEqual(result["status"], 401)
        result = self.api.request("GET", "/api/v1/fulfillments/f-1", {}, {})
        self.assertEqual(result["status"], 401)

    def test_customer_sees_own_fulfillment(self):
        result = self.api.request("GET", "/api/v1/fulfillments/f-1", {},
                                  self._headers("cust-token"))
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["fulfillment"]["id"], "f-1")

    def test_other_customer_cannot_read_detail(self):
        # Mirrors FastAPI: the service PermissionError becomes a 400 here.
        result = self.api.request("GET", "/api/v1/fulfillments/f-1", {},
                                  self._headers("other-token"))
        self.assertEqual(result["status"], 400)


if __name__ == "__main__":
    unittest.main()
