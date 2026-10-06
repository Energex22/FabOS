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

    def test_customer_design_asset_dimensions_block_undersized_printer(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            svc = ProductionService(db)
            printer_id = svc.ensure_default_vyper()
            with db.connect() as c:
                c.executescript("""
                    CREATE TABLE orders (id TEXT PRIMARY KEY, quote_id TEXT, status TEXT);
                    CREATE TABLE quote_designs (quote_id TEXT PRIMARY KEY, design_id TEXT);
                    CREATE TABLE designs (id TEXT PRIMARY KEY, current_version INTEGER);
                    CREATE TABLE design_versions (id TEXT PRIMARY KEY, design_id TEXT, version INTEGER);
                    CREATE TABLE design_assets (
                        id TEXT PRIMARY KEY, design_id TEXT, version_id TEXT,
                        width_mm REAL, depth_mm REAL, height_mm REAL, created_at TEXT DEFAULT CURRENT_TIMESTAMP
                    );
                """)
                c.execute("INSERT INTO orders(id,quote_id,status) VALUES(?,?,?)",
                          ("order-cad", "quote-cad", "confirmed"))
                c.execute("INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)",
                          ("quote-cad", "design-cad"))
                c.execute("INSERT INTO designs(id,current_version) VALUES(?,?)",
                          ("design-cad", 1))
                c.execute("INSERT INTO design_versions(id,design_id,version) VALUES(?,?,?)",
                          ("version-cad", "design-cad", 1))
                c.execute("""INSERT INTO design_assets(
                    id,design_id,version_id,width_mm,depth_mm,height_mm)
                    VALUES(?,?,?,?,?,?)""",
                          ("asset-cad", "design-cad", "version-cad", 300, 200, 100))
                c.execute("""INSERT INTO print_jobs(
                    id,order_id,product_id,variant_id,status,estimated_filament_g)
                    VALUES(?,?,?,?,?,?)""",
                          ("job-cad", "order-cad", None, None, "queued", 10))
                c.commit()
            with self.assertRaises(ValueError):
                svc.assign("job-cad", printer_id=printer_id)

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
