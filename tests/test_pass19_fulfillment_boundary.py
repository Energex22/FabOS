import os
import tempfile
import unittest

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.permissions import PermissionService


class Pass19FulfillmentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = Database(self.tmp.name)
        self.db.initialize()
        migrate(self.db)
        self.accounts = AccountService(self.db)
        self.permissions = PermissionService(self.db)
        self.fulfillment = FulfillmentService(self.db, self.accounts, self.permissions)
        with self.db.connect() as c:
            for uid, account_type in (("admin", "administrator"), ("employee", "employee"), ("customer1", "customer"), ("customer2", "customer")):
                c.execute("INSERT INTO users(id,username,password_hash,account_type,active) VALUES(?,?,?,?,1)",
                          (uid, uid, "x", account_type))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)",
                      ("cust1", "Customer One", "one@example.com", "", ""))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)",
                      ("cust2", "Customer Two", "two@example.com", "", ""))
            self._insert_order(c, "order1", "ORD-001", "cust1")
            self._insert_order(c, "order2", "ORD-002", "cust2")
            c.commit()
        self.accounts.link_customer("customer1", "cust1")
        self.accounts.link_customer("customer2", "cust2")
        self.fulfillment.ensure("order1", "shipping")
        self.fulfillment.ensure("order2", "shipping")

    def tearDown(self):
        try:
            os.unlink(self.tmp.name)
        except OSError:
            pass

    @staticmethod
    def _insert_order(c, order_id, number, customer_id):
        columns = {r[1]: r for r in c.execute("PRAGMA table_info(orders)").fetchall()}
        values = {"id": order_id, "order_number": number, "customer_id": customer_id, "status": "pending"}
        if "total_cents" in columns:
            values["total_cents"] = 1000
        cols = ["id", "order_number", "customer_id", "status"]
        if "total_cents" in columns:
            cols.append("total_cents")
        c.execute("INSERT INTO orders(%s) VALUES(%s)" %
                  (",".join(cols), ",".join("?" for _ in cols)),
                  tuple(values[x] for x in cols))

    def _id_for_order(self, order_id):
        with self.db.connect() as c:
            return c.execute("SELECT id FROM fulfillments WHERE order_id=?", (order_id,)).fetchone()["id"]

    def test_customer_can_only_read_own_fulfillment(self):
        own = self._id_for_order("order1")
        other = self._id_for_order("order2")
        self.assertEqual(self.fulfillment.get_for_user("customer1", own)["order_id"], "order1")
        with self.assertRaises(PermissionError):
            self.fulfillment.get_for_user("customer1", other)
        self.assertEqual([r["order_id"] for r in self.fulfillment.list_for_user("customer1")], ["order1"])

    def test_employee_and_admin_can_read_all_fulfillment(self):
        self.assertEqual(len(self.fulfillment.list_for_user("employee")), 2)
        self.assertEqual(len(self.fulfillment.list_for_user("admin")), 2)

    def test_customer_cannot_mutate_fulfillment(self):
        with self.assertRaises(PermissionError):
            self.fulfillment.ensure_for_user("customer1", "order1", "shipping")
        with self.assertRaises(PermissionError):
            self.fulfillment.save_for_user("customer1", "order1", "shipping", "shipped")

    def test_employee_can_manage_and_existing_status_logic_remains(self):
        fid = self.fulfillment.save_for_user("employee", "order1", "shipping", "shipped", tracking="TRACK-1")
        self.assertEqual(fid, self._id_for_order("order1"))
        with self.db.connect() as c:
            row = c.execute("SELECT status FROM orders WHERE id='order1'").fetchone()
            fulfillment = c.execute("SELECT status,tracking_number FROM fulfillments WHERE id=?", (fid,)).fetchone()
        self.assertEqual(row["status"], "shipped")
        self.assertEqual(fulfillment["tracking_number"], "TRACK-1")

    def test_fulfillment_manage_override_is_enforced(self):
        self.permissions.set_user_permission("employee", "fulfillment.manage", False)
        with self.assertRaises(PermissionError):
            self.fulfillment.save_for_user("employee", "order1", "shipping", "shipped")

    def test_customer_without_link_sees_no_rows(self):
        self.accounts.link_customer("customer1", "cust1")
        self.accounts.link_customer("customer2", "cust2")
        with self.db.connect() as c:
            c.execute("DELETE FROM customer_accounts WHERE user_id='customer2'")
            c.commit()
        self.assertEqual(self.fulfillment.list_for_user("customer2"), [])

    def test_dependencies_are_wired(self):
        self.assertIs(self.fulfillment.accounts, self.accounts)
        self.assertIs(self.fulfillment.permissions, self.permissions)


if __name__ == "__main__":
    unittest.main()
