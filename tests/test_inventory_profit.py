import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.inventory_profit import InventoryProfitService

class InventoryProfitTests(unittest.TestCase):
 def test_spool_consumption_is_idempotent(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   svc=InventoryProfitService(db)
   sid=svc.add_spool("PLA","Test","Black",1000,2000)
   jid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO print_jobs(id,spool_id,status,estimated_filament_g) VALUES(?,?,?,?)",(jid,sid,"completed",100));c.commit()
   svc.record_consumption(sid,100,jid);svc.record_consumption(sid,100,jid)
   with db.connect() as c:r=c.execute("SELECT remaining_g FROM filament_spools WHERE id=?",(sid,)).fetchone()
   self.assertAlmostEqual(r["remaining_g"],900)

 def test_cost_calculation(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   svc=InventoryProfitService(db);sid=svc.add_spool("PLA","Test","Black",1000,2000)
   oid=str(uuid.uuid4());jid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,total_cents) VALUES(?,?,?)",(oid,"O-1",2000))
    c.execute("""INSERT INTO print_jobs(id,order_id,spool_id,status,actual_minutes,actual_filament_g)
                 VALUES(?,?,?,?,?,?)""",(jid,oid,sid,"completed",60,100));c.commit()
   out=svc.calculate_job_cost(jid)
   self.assertEqual(out["material"],200)
   self.assertEqual(out["machine"],35)
   self.assertEqual(out["packaging"],50)
   self.assertEqual(out["profit"],1715)

if __name__=="__main__":unittest.main()
