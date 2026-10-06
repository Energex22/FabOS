import tempfile,unittest,uuid,json
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.manufacturing import ManufacturingService

class QCEditingTests(unittest.TestCase):
 def test_edit_rework_and_pass(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4());qid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"O-QC","qc"))
    c.execute("""INSERT INTO qc_inspections(id,order_id,status,checklist_json,notes)
                 VALUES(?,?,?,?,?)""",(qid,oid,"pending",json.dumps([{"text":"Old step","checked":False}]),"old"))
    c.commit()
   svc=ManufacturingService(db)
   edited=[{"text":"Surface finish checked","checked":True},{"text":"Packaging checked","checked":False}]
   svc.qc_update(qid,edited,"needs another look","rework")
   with db.connect() as c:r=c.execute("SELECT * FROM qc_inspections WHERE id=?",(qid,)).fetchone()
   self.assertEqual(r["status"],"rework")
   self.assertEqual(r["notes"],"needs another look")
   self.assertEqual(json.loads(r["checklist_json"])[0]["text"],"Surface finish checked")
   with self.assertRaises(ValueError):
    svc.qc_update(qid,[{"text":"Surface finish checked","checked":True},{"text":"Packaging checked","checked":False}],"not ready","passed")
   with self.assertRaises(ValueError):
    svc.qc_save(qid,[{"text":"Surface finish checked","checked":True},{"text":"Packaging checked","checked":False}],"not ready",True)
   passed=[{"text":"Surface finish checked","checked":True},{"text":"Packaging checked","checked":True}]
   svc.qc_update(qid,passed,"done","passed")
   with db.connect() as c:
    r=c.execute("SELECT status FROM qc_inspections WHERE id=?",(qid,)).fetchone()
    o=c.execute("SELECT status FROM orders WHERE id=?",(oid,)).fetchone()
   self.assertEqual(r["status"],"passed")
   self.assertEqual(o["status"],"ready")

 def test_reconcile_qc_ignores_cancelled_historical_jobs(self):
  with tempfile.TemporaryDirectory() as td:
   db=Database(Path(td)/"x.sqlite3");db.initialize();migrate(db)
   oid=str(uuid.uuid4());jid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",(oid,"O-QC-CANCELLED","qc"))
    c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",(jid,oid,"cancelled"))
    c.commit()
   svc=ManufacturingService(db)
   self.assertEqual(svc.reconcile_qc(),0)
   with db.connect() as c:
    count=c.execute("SELECT COUNT(*) FROM qc_inspections WHERE print_job_id=?",(jid,)).fetchone()[0]
   self.assertEqual(count,0)

if __name__=="__main__":unittest.main()
