import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.production import ProductionService
from fabos_core.services.cura_integration import CuraIntegrationService
from fabos_core.services.octoprint_print import OctoPrintPrintService
from fabos_desktop.product_print_ui import ProductPrintMixin
from fabos_desktop.production_ui import ProductionMixin

class FakeManufacturing:
 def __init__(self):self.calls=[]
 def octo(self,base,key,path,method='GET',body=None):
  self.calls.append((path,method,body))
  return {}

class DummyProductPrint:pass

class PrintWorkflow0126Tests(unittest.TestCase):
 def test_heater_targets_are_read_from_cura_gcode(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"x.gcode"
   p.write_text("M140 S80\nM104 S235\nM190 S80\nM109 S235\n",encoding="utf-8")
   result=CuraIntegrationService.gcode_heater_targets(p)
   self.assertEqual(result["bed"],80.0)
   self.assertEqual(result["hotend"],235.0)

 def test_preheat_queues_bed_and_hotend_without_waits(self):
  m=FakeManufacturing()
  svc=OctoPrintPrintService(m,DummyProductPrint())
  printer={"octoprint_url":"http://octopi","api_key_ref":"key"}
  result=svc.preheat_together(printer,235,80)
  self.assertEqual(result["commands"],["M140 S80","M104 S235"])
  self.assertIn(("/api/printer/command","POST",{"commands":["M140 S80","M104 S235"]}),m.calls)

 def test_catalog_can_attach_print_to_existing_order_job(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   pid=str(uuid.uuid4());oid=str(uuid.uuid4());jid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Widget","verified"))
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"ORD-100","production"))
    c.execute("INSERT INTO print_jobs(id,order_id,product_id,status) VALUES(?,?,?,?)",(jid,oid,pid,"queued"))
    c.commit()
   svc=ProductionService(db)
   orders=svc.attachable_orders(pid)
   self.assertTrue(any(r["id"]==oid for r in orders))
   job=svc.find_attachable_job(oid,pid)
   self.assertEqual(job["id"],jid)

 def test_order_only_advances_to_qc_after_all_jobs_complete(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   pid=str(uuid.uuid4());oid=str(uuid.uuid4());j1=str(uuid.uuid4());j2=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Widget","verified"))
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"ORD-200","production"))
    c.execute("INSERT INTO print_jobs(id,order_id,product_id,status) VALUES(?,?,?,?)",(j1,oid,pid,"printing"))
    c.execute("INSERT INTO print_jobs(id,order_id,product_id,status) VALUES(?,?,?,?)",(j2,oid,pid,"queued"))
    c.commit()
   svc=ProductionService(db)
   svc.set_status(j1,"completed")
   with db.connect() as c:
    self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()[0],"production")
   svc.set_status(j2,"completed")
   with db.connect() as c:
    self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()[0],"qc")

 def test_ui_is_import_only_and_live_production_refresh_exists(self):
  self.assertTrue(hasattr(ProductPrintMixin,"_import_cura_gcode_print"))
  self.assertTrue(hasattr(ProductionMixin,"_start_production_live_refresh"))
  source=(Path(__file__).resolve().parents[1]/"fabos_desktop"/"product_print_ui.py").read_text(encoding="utf-8")
  self.assertIn("Import Cura G-code",source)
  self.assertNotIn("Open in Cura / Import G-code",source)
  # The dialog no longer performs automatic Cura filesystem discovery at startup.
  startup=source[source.find("def _print_selected_product"):source.find("def selected_spool")]
  self.assertNotIn("find_cura(",startup)
  self.assertNotIn("installation_diagnostic(",startup)

if __name__=="__main__":
 unittest.main()
