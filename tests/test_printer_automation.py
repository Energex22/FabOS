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

if __name__=="__main__":unittest.main()
