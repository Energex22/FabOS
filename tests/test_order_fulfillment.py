import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.fulfillment import FulfillmentService
from fabos_desktop.commerce_ui import CommerceMixin

class FulfillmentTests(unittest.TestCase):
 def test_fulfillment_service(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4())
   with db.connect() as c:c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"O-1","ready"));c.commit()
   svc=FulfillmentService(db);svc.save(oid,"pickup","ready_for_pickup")
   self.assertEqual(svc.get_for_order(oid)["status"],"ready_for_pickup")
 def test_order_methods_are_on_commerce_mixin(self):
  for name in ("_build_orders_page","_order_dossier","_order_next_action","_order_fulfillment","_selected_order_id"):
   self.assertTrue(hasattr(CommerceMixin,name),name)

if __name__=="__main__":unittest.main()
