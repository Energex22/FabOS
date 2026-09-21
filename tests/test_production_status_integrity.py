import tempfile
import unittest
import uuid
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.production import ProductionService


class ProductionStatusIntegrityTests(unittest.TestCase):
    def test_completed_job_cannot_regress_to_printing(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/"fabos.sqlite3")
            db.initialize()
            migrate(db)
            job_id=str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO print_jobs(id,status) VALUES(?,?)",
                    (job_id,"completed"),
                )
                c.commit()
            with self.assertRaisesRegex(ValueError,"transition"):
                ProductionService(db).set_status(job_id,"printing")
            with db.connect() as c:
                self.assertEqual(
                    c.execute("SELECT status FROM print_jobs WHERE id=?",(job_id,)).fetchone()["status"],
                    "completed",
                )

    def test_cancelled_job_cannot_restart(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/"fabos.sqlite3")
            db.initialize()
            migrate(db)
            job_id=str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO print_jobs(id,status) VALUES(?,?)",(job_id,"cancelled"))
                c.commit()
            with self.assertRaisesRegex(ValueError,"transition"):
                ProductionService(db).set_status(job_id,"queued")

    def test_scheduled_job_can_start_printing(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/"fabos.sqlite3")
            db.initialize()
            migrate(db)
            job_id=str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO print_jobs(id,status) VALUES(?,?)",(job_id,"scheduled"))
                c.commit()
            ProductionService(db).set_status(job_id,"printing")
            with db.connect() as c:
                self.assertEqual(
                    c.execute("SELECT status FROM print_jobs WHERE id=?",(job_id,)).fetchone()["status"],
                    "printing",
                )


if __name__=="__main__":
    unittest.main()
