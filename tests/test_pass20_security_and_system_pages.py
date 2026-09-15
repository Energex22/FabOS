import os
import tempfile
import unittest

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.permissions import PermissionService
from fabos_core.services.security import SecurityService
from fabos_core.services.orders import OrderService
from fabos_desktop.system_ui_v20 import safe_activity_rows, safe_log_rows


class _AuthStub:
    def authenticate(self, token):
        if token == "valid":
            return {"user_id": "employee", "token": token}
        return None


class _FailingActivity:
    def recent_activity(self, limit):
        raise RuntimeError("journal unavailable")


class _FailingLog:
    def recent(self, limit):
        raise RuntimeError("log unavailable")


class Pass20SecurityAndSystemPageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(self.tmp.name)
        self.db.initialize()
        migrate(self.db)
        self.accounts = AccountService(self.db)
        self.permissions = PermissionService(self.db)
        self.security = SecurityService(self.db, _AuthStub(), self.accounts, self.permissions)
        self.orders = OrderService(self.db, self.accounts, self.permissions)
        with self.db.connect() as c:
            c.execute("INSERT INTO users(id,username,password_hash,account_type,active) VALUES(?,?,?,?,1)",
                      ("employee", "employee", "x", "employee"))
            c.execute("INSERT INTO users(id,username,password_hash,account_type,active) VALUES(?,?,?,?,1)",
                      ("customer", "customer", "x", "customer"))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)",
                      ("cust1", "Customer", "c@example.com", "", ""))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)",
                      ("cust2", "Other", "o@example.com", "", ""))
            c.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                      ("order1", "ORD-001", "cust1", "pending", 1000))
            c.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                      ("order2", "ORD-002", "cust2", "pending", 1000))
            c.commit()
        self.accounts.link_customer("customer", "cust1")

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    def test_authenticated_context_and_permission_boundary(self):
        context = self.security.context("valid", "order.read")
        self.assertEqual(context["user"]["id"], "employee")
        self.assertEqual(context["session"]["user_id"], "employee")
        with self.assertRaises(PermissionError):
            self.security.context("invalid")

    def test_customer_order_scope_isolated(self):
        self.assertTrue(self.security.order_scope("customer", "order1"))
        self.assertFalse(self.security.order_scope("customer", "order2"))
        with self.assertRaises(PermissionError):
            self.security.require_order_scope("customer", "order2")

    def test_trusted_internal_order_transition_still_validates_graph(self):
        row = self.orders.set_status_internal("order1", "confirmed", reason="activity undo test")
        self.assertEqual(row["status"], "confirmed")
        with self.assertRaises(ValueError):
            self.orders.set_status_internal("order1", "completed")

    def test_system_page_reads_fail_soft(self):
        activity = safe_activity_rows(_FailingActivity())
        logs = safe_log_rows(_FailingLog())
        self.assertEqual(activity[0]["event_type"], "ERROR")
        self.assertIn("journal unavailable", activity[0]["detail"])
        self.assertEqual(logs[0]["level"], "ERROR")
        self.assertIn("log unavailable", logs[0]["detail"])


if __name__ == "__main__":
    unittest.main()
