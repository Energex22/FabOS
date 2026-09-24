import os
import tempfile
import unittest
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.services.production import ProductionService

class ProductionTests(unittest.TestCase):
    def test_default_printer_and_status(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            svc = ProductionService(db)
            svc.ensure_default_vyper()
            printers = svc.printers()
            self.assertEqual(len(printers), 1)
            self.assertEqual(printers[0]["name"], "Anycubic Vyper")

    def test_completing_job_does_not_hide_another_active_job_on_same_printer(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            svc = ProductionService(db)
            printer_id = svc.ensure_default_vyper()
            first = "job-first"
            second = "job-second"
            with db.connect() as c:
                c.execute(
                    "INSERT INTO print_jobs(id,printer_id,status,estimated_filament_g) VALUES(?,?,?,?)",
                    (first, printer_id, "printing", 10),
                )
                c.execute(
                    "INSERT INTO print_jobs(id,printer_id,status,estimated_filament_g) VALUES(?,?,?,?)",
                    (second, printer_id, "printing", 10),
                )
                c.commit()
            svc.set_status(first, "completed")
            with db.connect() as c:
                printer = c.execute("SELECT status FROM printers WHERE id=?", (printer_id,)).fetchone()
            self.assertEqual(printer["status"], "printing")

if __name__ == "__main__":
    unittest.main()
