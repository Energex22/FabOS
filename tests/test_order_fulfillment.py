import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.manufacturing import ManufacturingService
from fabos_core.services.orders import OrderService
from fabos_desktop.commerce_ui import CommerceMixin

class FulfillmentTests(unittest.TestCase):
 def test_fulfillment_service(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4())
   with db.connect() as c:c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"O-1","ready"));c.commit()
   svc=FulfillmentService(db);svc.save(oid,"pickup","ready_for_pickup")
   self.assertEqual(svc.get_for_order(oid)["status"],"ready_for_pickup")
 def test_order_cannot_be_completed_until_invoice_is_fully_paid(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,"O-2","ready",1000))
    c.execute("INSERT INTO invoices(id,invoice_number,order_id,status,subtotal_cents,tax_cents,shipping_cents,discount_cents,total_cents,paid_cents) VALUES(?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),"INV-2",oid,"open",1000,0,0,0,1000,0))
    c.commit()
   svc=OrderService(db)
   with self.assertRaises(ValueError):
    svc.set_status_internal(oid,"completed")
   with db.connect() as c:
    c.execute("UPDATE invoices SET paid_cents=1000,status='paid' WHERE order_id=?",(oid,));c.commit()
   svc.set_status_internal(oid,"completed")
   self.assertEqual(svc.get(oid)[0]["status"],"completed")
 def test_production_order_cannot_complete_before_fulfillment(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4());jid=str(uuid.uuid4());qid=str(uuid.uuid4());fid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,"O-GATE","ready",1000))
    c.execute("INSERT INTO invoices(id,invoice_number,order_id,status,subtotal_cents,tax_cents,shipping_cents,discount_cents,total_cents,paid_cents) VALUES(?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),"INV-GATE",oid,"paid",1000,0,0,0,1000,1000))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(jid,oid,"completed"))
    c.execute("INSERT INTO qc_inspections(id,order_id,print_job_id,status) VALUES(?,?,?,'passed')",(qid,oid,jid))
    c.commit()
   svc=OrderService(db)
   with self.assertRaisesRegex(ValueError,"production, QC, and fulfillment"):
    svc.set_status_internal(oid,"completed")
   FulfillmentService(db).save(oid,"pickup","ready_for_pickup")
   with self.assertRaises(ValueError):
    svc.set_status_internal(oid,"completed")
   FulfillmentService(db).save(oid,"pickup","picked_up")
   svc.set_status_internal(oid,"completed")
   self.assertEqual(svc.get(oid)[0]["status"],"completed")

 def test_production_order_cannot_complete_with_unfinished_print_job(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,"O-JOB-GATE","ready",1000))
    c.execute("INSERT INTO invoices(id,invoice_number,order_id,status,subtotal_cents,tax_cents,shipping_cents,discount_cents,total_cents,paid_cents) VALUES(?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),"INV-JOB-GATE",oid,"paid",1000,0,0,0,1000,1000))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(str(uuid.uuid4()),oid,"completed"))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(str(uuid.uuid4()),oid,"queued"))
    c.commit()
   with self.assertRaisesRegex(ValueError,"production, QC, and fulfillment"):
    OrderService(db).set_status_internal(oid,"completed")

 def test_record_payment_cannot_bypass_production_completion_gates(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4());jid=str(uuid.uuid4());qid=str(uuid.uuid4());iid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,"O-PAY-GATE","ready",1000))
    c.execute("INSERT INTO invoices(id,invoice_number,order_id,status,subtotal_cents,tax_cents,shipping_cents,discount_cents,total_cents,paid_cents) VALUES(?,?,?,?,?,?,?,?,?,?)",(iid,"INV-PAY-GATE",oid,"open",1000,0,0,0,1000,0))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(jid,oid,"completed"))
    c.execute("INSERT INTO qc_inspections(id,order_id,print_job_id,status) VALUES(?,?,?,'passed')",(qid,oid,jid))
    c.commit()
   from fabos_core.services.invoices import InvoiceService
   InvoiceService(db,Path(td)/"data").record_payment(iid,1000,method="test",reference="pay-gate")
   self.assertEqual(OrderService(db).get(oid)[0]["status"],"ready")

 def test_cancelling_order_cancels_queued_jobs_but_not_active_prints(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4());queued=str(uuid.uuid4());printing=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"O-CANCEL","in_production"))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(queued,oid,"queued"))
    c.execute("INSERT INTO print_jobs(id,order_id,status,started_at) VALUES(?,?,?,CURRENT_TIMESTAMP)",(printing,oid,"printing"))
    c.commit()
   with self.assertRaisesRegex(ValueError,"actively printing"):
    OrderService(db).set_status_internal(oid,"cancelled")
   with db.connect() as c:
    c.execute("UPDATE print_jobs SET status='queued',started_at=NULL WHERE id=?",(printing,));c.commit()
   OrderService(db).set_status_internal(oid,"cancelled")
   with db.connect() as c:
    self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()[0],"cancelled")
    statuses={r["status"] for r in c.execute("SELECT status FROM print_jobs WHERE order_id=?",(oid,)).fetchall()}
   self.assertEqual(statuses,{"cancelled"})

 def test_reprint_reopens_terminal_fulfillment_before_replacement_can_complete(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4());old_job=str(uuid.uuid4());old_qc=str(uuid.uuid4());fid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",(oid,"O-REPRINT-FULFILL","completed",1000))
    c.execute("INSERT INTO invoices(id,invoice_number,order_id,status,subtotal_cents,tax_cents,shipping_cents,discount_cents,total_cents,paid_cents) VALUES(?,?,?,?,?,?,?,?,?,?)",(str(uuid.uuid4()),"INV-REPRINT-FULFILL",oid,"paid",1000,0,0,0,1000,1000))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(old_job,oid,"completed"))
    c.execute("INSERT INTO qc_inspections(id,order_id,print_job_id,status) VALUES(?,?,?,'passed')",(old_qc,oid,old_job))
    c.execute("INSERT INTO fulfillments(id,order_id,method,status,delivered_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",(fid,oid,"shipping","delivered"))
    c.commit()
   replacement=ManufacturingService(db).reprint(old_job)
   with db.connect() as c:
    self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()[0],"in_production")
    self.assertEqual(c.execute("SELECT status FROM fulfillments WHERE order_id=?",(oid,)).fetchone()[0],"pending")
    c.execute("UPDATE print_jobs SET status='completed',completed_at=CURRENT_TIMESTAMP,success=1 WHERE id=?",(replacement,))
    c.execute("INSERT INTO qc_inspections(id,order_id,print_job_id,status) VALUES(?,?,?,'passed')",(str(uuid.uuid4()),oid,replacement))
    c.execute("UPDATE orders SET status='ready' WHERE id=?",(oid,))
    c.commit()
   with self.assertRaisesRegex(ValueError,"production, QC, and fulfillment"):
    OrderService(db).set_status_internal(oid,"completed")
   FulfillmentService(db).save(oid,"shipping","shipped",carrier="Test")
   FulfillmentService(db).save(oid,"shipping","delivered",carrier="Test")
   OrderService(db).set_status_internal(oid,"completed")
   self.assertEqual(OrderService(db).get(oid)[0]["status"],"completed")

 def test_order_methods_are_on_commerce_mixin(self):
  for name in ("_build_orders_page","_order_dossier","_order_next_action","_order_fulfillment","_selected_order_id"):
   self.assertTrue(hasattr(CommerceMixin,name),name)

if __name__=="__main__":unittest.main()
