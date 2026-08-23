import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.invoices import InvoiceService

class InvoiceTests(unittest.TestCase):
 def test_order_invoice_and_partial_payment(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   cid=str(uuid.uuid4());oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO customers(id,name) VALUES(?,?)",(cid,"Invoice Customer"))
    c.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",(oid,"O-100",cid,"ready",2500))
    c.commit()
   svc=InvoiceService(db,Path(td))
   iid,new=svc.create_from_order(oid)
   self.assertTrue(new)
   _,new2=svc.create_from_order(oid)
   self.assertFalse(new2)
   svc.record_payment(iid,1000,"Cash")
   inv,_,pays=svc.get(iid)
   self.assertEqual(inv["status"],"partial")
   self.assertEqual(inv["paid_cents"],1000)
   self.assertEqual(inv["balance_cents"],1500)
   self.assertEqual(len(pays),1)
   svc.record_payment(iid,1500,"Cash")
   inv,_,_=svc.get(iid)
   self.assertEqual(inv["status"],"paid")
   with db.connect() as c:o=c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()
   # Payment alone no longer skips packing/shipping; fulfillment completes the lifecycle.
   self.assertEqual(o["status"],"ready")

 def test_invoice_charges_and_export(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,total_cents) VALUES(?,?,?)",(oid,"O-200",1000));c.commit()
   svc=InvoiceService(db,Path(td))
   iid,_=svc.create_from_order(oid)
   svc.update_charges(iid,80,500,100,"Thank you")
   inv,_,_=svc.get(iid)
   self.assertEqual(inv["total_cents"],1480)
   path=svc.export_html(iid)
   self.assertTrue(path.exists())
   self.assertIn("1480",str(inv["total_cents"]))

if __name__=="__main__":unittest.main()
