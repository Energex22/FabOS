import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.fulfillment import FulfillmentService
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
 def test_order_methods_are_on_commerce_mixin(self):
  for name in ("_build_orders_page","_order_dossier","_order_next_action","_order_fulfillment","_selected_order_id"):
   self.assertTrue(hasattr(CommerceMixin,name),name)

if __name__=="__main__":unittest.main()
