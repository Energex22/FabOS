import os
import tempfile
import unittest

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.orders import OrderService
from fabos_core.services.permissions import PermissionService


class Pass17OrderAccessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False); self.tmp.close()
        self.db = Database(self.tmp.name); migrate(self.db)
        self.accounts = AccountService(self.db); self.permissions = PermissionService(self.db)
        self.orders = OrderService(self.db, self.accounts, self.permissions)
        with self.db.connect() as c:
            for row in [("admin","admin","administrator"),("employee","employee","employee"),("customer1","customer1","customer"),("customer2","customer2","customer")]:
                c.execute("INSERT INTO users(id,username,password_hash,account_type,active) VALUES(?,?,?,?,1)", row+ ("x",) if False else (row[0],row[1],"x",row[2]))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", ("cust1","Customer One","one@example.com","",""))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", ("cust2","Customer Two","two@example.com","","")); c.commit()
        self.accounts.link_customer("customer1","cust1"); self.accounts.link_customer("customer2","cust2")
        self._insert_order("order1","ORD-001","cust1","pending"); self._insert_order("order2","ORD-002","cust2","pending")

    def tearDown(self):
        try: os.unlink(self.tmp.name)
        except OSError: pass

    def _insert_order(self, order_id, number, customer_id, status):
        with self.db.connect() as c:
            columns={r[1]:r for r in c.execute("PRAGMA table_info(orders)").fetchall()}
            values={"id":order_id,"order_number":number,"customer_id":customer_id,"status":status}
            if "total_cents" in columns: values["total_cents"]=0
            cols=["id","order_number","customer_id","status"]
            if "total_cents" in columns: cols.append("total_cents")
            c.execute("INSERT INTO orders(%s) VALUES(%s)" % (",".join(cols),",".join("?" for _ in cols)), tuple(values[x] for x in cols)); c.commit()

    def test_customer_isolation(self):
        self.assertEqual(self.orders.get_for_user("customer1","order1")[0]["id"],"order1")
        with self.assertRaises(PermissionError): self.orders.get_for_user("customer1","order2")
        self.assertEqual([r["id"] for r in self.orders.list_for_user("customer1")],["order1"])

    def test_employee_and_admin_can_read_orders(self):
        self.assertEqual(self.orders.get_for_user("employee","order2")[0]["id"],"order2")
        self.assertEqual(self.orders.get_for_user("admin","order1")[0]["id"],"order1")

    def test_customer_cannot_mutate_orders(self):
        with self.assertRaises(PermissionError): self.orders.set_status("order1","confirmed",actor_user_id="customer1")

    def test_valid_and_invalid_transitions(self):
        self.orders.set_status("order1","confirmed",actor_user_id="employee")
        self.orders.set_status("order1","in_production",actor_user_id="employee")
        with self.assertRaises(ValueError): self.orders.set_status("order1","completed",actor_user_id="employee")
        self.orders.set_status("order1","ready",actor_user_id="employee")
        self.orders.set_status("order1","completed",actor_user_id="employee")
        with self.assertRaises(ValueError): self.orders.set_status("order1","pending",actor_user_id="employee")

    def test_status_change_requires_actor(self):
        with self.assertRaises(PermissionError): self.orders.set_status("order1","confirmed")


if __name__ == "__main__": unittest.main()
