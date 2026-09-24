import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.production import ProductionService
from fabos_core.services.manufacturing import ManufacturingService
from fabos_core.services.printer_automation import PrinterAutomationService

class PrinterAutomationTests(unittest.TestCase):
 def test_simulation_and_filament_deduction(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   prod=ProductionService(db);pid=prod.ensure_default_vyper()
   m=ManufacturingService(db);svc=PrinterAutomationService(db,prod,m)
   spool=str(uuid.uuid4());job=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO filament_spools(id,material,color,initial_g,remaining_g) VALUES(?,?,?,?,?)",(spool,"PLA","Black",1000,1000))
    c.execute("INSERT INTO print_jobs(id,printer_id,spool_id,status,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?)",(job,pid,spool,"scheduled",60,50))
    c.commit()
   svc.start_simulation(pid,job)
   for _ in range(10):svc.simulation_tick(pid,10)
   with db.connect() as c:
    j=c.execute("SELECT * FROM print_jobs WHERE id=?",(job,)).fetchone()
    s=c.execute("SELECT * FROM filament_spools WHERE id=?",(spool,)).fetchone()
   self.assertEqual(j["status"],"completed")
   self.assertEqual(j["filament_deducted"],1)
   self.assertAlmostEqual(s["remaining_g"],950)


 def test_idle_octoprint_with_unconfirmed_active_job_creates_mismatch_alert(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   prod=ProductionService(db);m=ManufacturingService(db)
   svc=PrinterAutomationService(db,prod,m)
   pid=str(uuid.uuid4());job=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("""INSERT INTO printers
      (id,name,status,connection_mode,octoprint_url,api_key_ref)
      VALUES(?,?,?,?,?,?)""",(pid,"Mismatch Test","printing","octoprint","http://octoprint","key"))
    c.execute("""INSERT INTO print_jobs
      (id,printer_id,status,estimated_filament_g,octoprint_file)
      VALUES(?,?,?,?,?)""",(job,pid,"printing",20,"expected.gcode"))
    c.commit()

   class FakeManufacturing:
    def octo(self,base,key,path,method="GET",body=None):
     if path=="/api/connection":
      return {"current":{"state":"Operational"}}
     if path=="/api/printer?history=true&limit=2":
      import time
      return {"temperature":{"tool0":{"actual":200},"bed":{"actual":60},
                              "history":[{"time":time.time(),"tool0":{"actual":200}}]}}
     raise AssertionError(path)
    def octo_job(self,base,key):
     return {"state":"Operational","job":{"file":{"name":"different.gcode"}},
             "progress":{"completion":50,"printTime":60,"printTimeLeft":60}}

   svc.m=FakeManufacturing()
   svc.sync_octoprint(pid)
   with db.connect() as c:
    note=c.execute("SELECT severity,title,body FROM notifications WHERE dedupe_key=?",
                   ("event:octoprint:mismatch:"+job,)).fetchone()
   self.assertIsNotNone(note)
   self.assertEqual(note["severity"],"high")
   self.assertIn("different file",note["body"].lower())

 def test_octoprint_active_without_matching_fabos_job_creates_alert(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();m=ManufacturingService(db)
   prod=ProductionService(db);svc=PrinterAutomationService(db,prod,m)
   pid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("""INSERT INTO printers
      (id,name,status,connection_mode,octoprint_url,api_key_ref)
      VALUES(?,?,?,?,?,?)""",(pid,"Orphan Test","idle","octoprint","http://octoprint","key"))
    c.commit()

   class FakeManufacturing:
    def octo(self,base,key,path,method="GET",body=None):
     if path=="/api/connection":
      return {"current":{"state":"Operational"}}
     if path=="/api/printer?history=true&limit=2":
      import time
      return {"temperature":{"tool0":{"actual":200},"bed":{"actual":60},
                              "history":[{"time":time.time(),"tool0":{"actual":200}}]}}
     raise AssertionError(path)
    def octo_job(self,base,key):
     return {"state":"Printing","job":{"file":{"name":"external.gcode"}},
             "progress":{"completion":25,"printTime":120,"printTimeLeft":360}}

   svc.m=FakeManufacturing()
   svc.sync_octoprint(pid)
   with db.connect() as c:
    note=c.execute("SELECT severity,title,body FROM notifications WHERE dedupe_key=?",
                   ("event:octoprint:active-mismatch:"+pid,)).fetchone()
   self.assertIsNotNone(note)
   self.assertEqual(note["severity"],"high")
   self.assertIn("no matching active job",note["body"].lower())


if __name__=="__main__":unittest.main()
