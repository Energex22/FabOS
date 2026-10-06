import os
import tempfile
import unittest
import sqlite3
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
            conn = sqlite3.connect(":memory:")
            conn.row_factory = sqlite3.Row
            conn.executescript("""
                CREATE TABLE orders (id TEXT, quote_id TEXT);
                CREATE TABLE quote_designs (quote_id TEXT, design_id TEXT);
                CREATE TABLE designs (id TEXT, current_version INTEGER);
                CREATE TABLE design_versions (id TEXT, design_id TEXT, version INTEGER);
                CREATE TABLE design_assets (
                    id TEXT, design_id TEXT, version_id TEXT,
                    width_mm REAL, depth_mm REAL, height_mm REAL, created_at TEXT
                );
            """)
            conn.execute("INSERT INTO orders VALUES(?,?)", ("order-cad", "quote-cad"))
            conn.execute("INSERT INTO quote_designs VALUES(?,?)", ("quote-cad", "design-cad"))
            conn.execute("INSERT INTO designs VALUES(?,?)", ("design-cad", 1))
            conn.execute("INSERT INTO design_versions VALUES(?,?,?)", ("version-cad", "design-cad", 1))
            conn.execute("INSERT INTO design_assets VALUES(?,?,?,?,?,?,?)",
                         ("asset-cad", "design-cad", "version-cad", 300, 200, 100, "2026-10-06"))
            conn.commit()
            job = {"product_id": None, "order_id": "order-cad"}
            dimensions = svc._design_dimensions(conn, job)
            self.assertEqual(dimensions, (300.0, 200.0, 100.0))
            with db.connect() as c:
                printer = c.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone()
            self.assertFalse(svc._printer_supports_dimensions(printer, dimensions))
            conn.close()

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
