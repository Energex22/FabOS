import os
import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.permissions import PermissionService


class Pass18PaymentBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.data_dir = tempfile.mkdtemp()
        self.db = Database(self.tmp.name)
        self.db.initialize()
        migrate(self.db)
        self.accounts = AccountService(self.db)
        self.permissions = PermissionService(self.db)
        self.invoices = InvoiceService(self.db, self.data_dir, self.accounts, self.permissions)
        with self.db.connect() as c:
            users = [("admin", "admin", "administrator"), ("employee", "employee", "employee"), ("customer1", "customer1", "customer"), ("customer2", "customer2", "customer")]
            for uid, username, account_type in users:
                c.execute("INSERT INTO users(id,username,password_hash,account_type,active) VALUES(?,?,?,?,1)", (uid, username, "x", account_type))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", ("cust1", "Customer One", "one@example.com", "", ""))
            c.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", ("cust2", "Customer Two", "two@example.com", "", ""))
            c.commit()
        self.accounts.link_customer("customer1", "cust1")
        self.accounts.link_customer("customer2", "cust2")
        self._insert_order("order1", "ORD-001", "cust1")
        self._insert_order("order2", "ORD-002", "cust2")
        self._insert_invoice("inv1", "INV-001", "order1", 1000)
        self._insert_invoice("inv2", "INV-002", "order2", 2000)

    def tearDown(self):
        try: os.unlink(self.tmp.name)
        except OSError: pass
        try:
            import shutil; shutil.rmtree(self.data_dir)
        except OSError: pass

    def _insert_order(self, order_id, number, customer_id):
        with self.db.connect() as c:
            columns={r[1]:r for r in c.execute("PRAGMA table_info(orders)").fetchall()}
            values={"id":order_id,"order_number":number,"customer_id":customer_id,"status":"pending"}
            if "total_cents" in columns: values["total_cents"]=1000
            cols=["id","order_number","customer_id","status"]
            if "total_cents" in columns: cols.append("total_cents")
            c.execute("INSERT INTO orders(%s) VALUES(%s)" % (",".join(cols),",".join("?" for _ in cols)), tuple(values[x] for x in cols)); c.commit()

    def _insert_invoice(self, invoice_id, number, order_id, total):
        with self.db.connect() as c:
            columns={r[1]:r for r in c.execute("PRAGMA table_info(invoices)").fetchall()}
            values={"id":invoice_id,"invoice_number":number,"order_id":order_id,"status":"open","total_cents":total,"paid_cents":0}
            for name,info in columns.items():
                if name in values or info[5]==1 or info[4] is not None or info[3]==0: continue
                if name.endswith("_at") or name=="due_at": values[name]="2026-01-01T00:00:00"
                elif name.endswith("_cents"): values[name]=0
                else: values[name]=""
            cols=[name for name in columns if name in values]
            c.execute("INSERT INTO invoices(%s) VALUES(%s)" % (",".join(cols),",".join("?" for _ in cols)),tuple(values[name] for name in cols)); c.commit()

    def test_customer_can_only_read_own_invoices(self):
        self.assertEqual(self.invoices.get_for_user("customer1","inv1")[0]["id"],"inv1")
        with self.assertRaises(PermissionError): self.invoices.get_for_user("customer1","inv2")
        self.assertEqual([row["id"] for row in self.invoices.list_for_user("customer1")],["inv1"])

    def test_employee_and_admin_can_read_all_invoices(self):
        self.assertEqual(self.invoices.get_for_user("employee","inv2")[0]["id"],"inv2")
        self.assertEqual(self.invoices.get_for_user("admin","inv1")[0]["id"],"inv1")

    def test_customer_cannot_create_or_modify_invoice(self):
        with self.assertRaises(PermissionError): self.invoices.create_from_order_for_user("customer1","order1")
        with self.assertRaises(PermissionError): self.invoices.update_charges_for_user("customer1","inv1",tax_cents=100)
        with self.assertRaises(PermissionError): self.invoices.record_payment_for_user("customer1","inv1",100)
        with self.assertRaises(PermissionError): self.invoices.void_for_user("customer1","inv1")

    def test_employee_can_record_payment(self):
        self.invoices.record_payment_for_user("employee","inv1",1000,method="cash")
        invoice=self.invoices.get_for_user("employee","inv1")[0]
        self.assertEqual(invoice["paid_cents"],1000); self.assertEqual(invoice["status"],"paid")

    def test_payment_read_permission_is_enforced(self):
        self.permissions.set_user_permission("employee","payment.read",False)
        with self.assertRaises(PermissionError): self.invoices.get_for_user("employee","inv1")

    def test_application_invoice_dependencies_are_wired(self):
        self.assertIs(self.invoices.accounts,self.accounts); self.assertIs(self.invoices.permissions,self.permissions); self.assertTrue(Path(self.data_dir).exists())

if __name__ == "__main__": unittest.main()
