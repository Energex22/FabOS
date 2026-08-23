import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.orders import OrderService
from fabos_core.services.fulfillment import FulfillmentService
from fabos_desktop.main import FabOSDesktop

class OrderHistoryTabTests(unittest.TestCase):
 def make_order(self,db,number,status="new"):
  oid=str(uuid.uuid4())
  with db.connect() as c:
   c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
             (oid,number,status));c.commit()
  return oid

 def test_active_and_history_are_separated(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   active=self.make_order(db,"ORD-A","production")
   completed=self.make_order(db,"ORD-C","completed")
   cancelled=self.make_order(db,"ORD-X","cancelled")
   svc=OrderService(db)
   active_ids={r["id"] for r in svc.list(group="active")}
   history_ids={r["id"] for r in svc.list(group="history")}
   self.assertIn(active,active_ids)
   self.assertNotIn(completed,active_ids)
   self.assertNotIn(cancelled,active_ids)
   self.assertIn(completed,history_ids)
   self.assertIn(cancelled,history_ids)

 def test_shipped_order_moves_to_history_immediately(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=self.make_order(db,"ORD-S","ready")
   FulfillmentService(db).save(
    oid,"shipping","shipped","UPS","1ZTEST",None,500,"Customer address")
   svc=OrderService(db)
   self.assertNotIn(oid,{r["id"] for r in svc.list(group="active")})
   history={r["id"]:r for r in svc.list(group="history")}
   self.assertIn(oid,history)
   self.assertEqual(history[oid]["display_status"],"shipped")

 def test_delivered_unpaid_stays_history_not_active(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=self.make_order(db,"ORD-D","ready")
   f=FulfillmentService(db)
   f.save(oid,"shipping","delivered","USPS","TRACK",None,0,"Destination")
   svc=OrderService(db)
   self.assertNotIn(oid,{r["id"] for r in svc.list(group="active")})
   row=next(r for r in svc.list(group="history") if r["id"]==oid)
   self.assertEqual(row["display_status"],"delivered")

 def test_order_history_ui_methods_are_wired(self):
  self.assertTrue(hasattr(FabOSDesktop,"_switch_order_view"))
  self.assertTrue(hasattr(FabOSDesktop,"_style_order_tabs"))

if __name__=="__main__":
 unittest.main()
