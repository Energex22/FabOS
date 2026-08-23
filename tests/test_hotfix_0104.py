import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.manufacturing import ManufacturingService
from fabos_desktop.manufacturing_ui import ManufacturingMixin

class Hotfix0104Tests(unittest.TestCase):
 def test_qc_methods_are_on_mixin(self):
  self.assertTrue(hasattr(ManufacturingMixin,"_build_qc_page"))
  self.assertTrue(hasattr(ManufacturingMixin,"_qc_refresh"))
  self.assertTrue(hasattr(ManufacturingMixin,"_qc_inspect"))

 def test_qc_reconcile(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4());jid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"O-QC","qc"))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(jid,oid,"completed"));c.commit()
   svc=ManufacturingService(db)
   self.assertEqual(svc.reconcile_qc(),1)
   self.assertEqual(len(svc.qc_list()),1)
   self.assertEqual(svc.reconcile_qc(),0)

if __name__=="__main__":unittest.main()
