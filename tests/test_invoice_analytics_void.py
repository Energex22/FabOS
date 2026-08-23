import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.invoices import InvoiceService

class InvoiceAnalyticsVoidTests(unittest.TestCase):
 def test_paid_invoice_appears_in_finance_summary_and_cannot_void(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,total_cents,status) VALUES(?,?,?,?)",(oid,"O-PAID",2500,"ready"));c.commit()
   svc=InvoiceService(db,Path(td))
   iid,_=svc.create_from_order(oid)
   svc.record_payment(iid,2500,"Cash")
   summary=svc.finance_summary()
   self.assertEqual(summary["paid_revenue_cents"],2500)
   self.assertEqual(summary["paid_invoices"],1)
   self.assertEqual(summary["outstanding_cents"],0)
   with self.assertRaises(ValueError) as cm:
    svc.void(iid)
   self.assertIn("recorded payments",str(cm.exception))

 def test_reconcile_uses_payment_ledger(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,total_cents) VALUES(?,?,?)",(oid,"O-R",1000));c.commit()
   svc=InvoiceService(db,Path(td))
   iid,_=svc.create_from_order(oid)
   svc.record_payment(iid,1000,"Cash")
   with db.connect() as c:
    c.execute("UPDATE invoices SET paid_cents=0,status='open' WHERE id=?",(iid,));c.commit()
   svc.reconcile(iid)
   inv,_,_=svc.get(iid)
   self.assertEqual(inv["paid_cents"],1000)
   self.assertEqual(inv["status"],"paid")

if __name__=="__main__":unittest.main()
