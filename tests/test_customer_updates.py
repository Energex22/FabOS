import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.customer_updates import CustomerUpdateService
from fabos_desktop.commerce_ui import CommerceMixin

class CustomerUpdateTests(unittest.TestCase):
 def test_generate_and_log_update(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   cid=str(uuid.uuid4());oid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO customers(id,name,email) VALUES(?,?,?)",(cid,"Sam","sam@example.com"))
    c.execute("INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,0)",(oid,"O-10",cid,"new"))
    c.commit()
   svc=CustomerUpdateService(db)
   msg=svc.generate(oid)
   self.assertIn("O-10",msg["subject"])
   self.assertIn("Sam",msg["body"])
   mid=svc.save(oid,msg["message_type"],msg["subject"],msg["body"],"clipboard","sent")
   hist=svc.history(oid)
   self.assertEqual(len(hist),1)
   self.assertEqual(hist[0]["status"],"sent")
   self.assertEqual(hist[0]["id"],mid)

 def test_order_ui_has_customer_update(self):
  self.assertTrue(hasattr(CommerceMixin,"_order_customer_update"))

if __name__=="__main__":unittest.main()
