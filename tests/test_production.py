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
            user_id = "user-cad"
            customer_id = "customer-cad"
            quote_id = "quote-cad"
            order_id = "order-cad"
            design_id = "design-cad"
            version_id = "version-cad"
            asset_id = "asset-cad"
            job_id = "job-cad"
            with db.connect() as c:
                c.execute("INSERT INTO users(id,email,password_hash,account_type) VALUES(?,?,?,?)",
                          (user_id, "cad@example.test", "x", "customer"))
                c.execute("INSERT INTO customers(id,name) VALUES(?,?)", (customer_id, "CAD Customer"))
                c.execute("INSERT INTO customer_accounts(id,user_id,customer_id) VALUES(?,?,?)",
                          ("ca-cad", user_id, customer_id))
                c.execute("INSERT INTO quotes(id,quote_number,customer_id,status) VALUES(?,?,?,?)",
                          (quote_id, "Q-CAD", customer_id, "approved"))
                c.execute("INSERT INTO orders(id,quote_id,customer_id,status) VALUES(?,?,?,?)",
                          (order_id, quote_id, customer_id, "confirmed"))
                c.execute("INSERT INTO designs(id,name,current_version) VALUES(?,?,?)",
                          (design_id, "AI CAD", 1))
                c.execute("INSERT INTO design_versions(id,design_id,version,label) VALUES(?,?,?,?)",
                          (version_id, design_id, 1, "AI Generated"))
                c.execute("""INSERT INTO design_assets(
                    id,design_id,version_id,kind,original_name,stored_path,sha256,bytes,width_mm,depth_mm,height_mm)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                          (asset_id, design_id, version_id, "model", "model.stl", "/tmp/model.stl", "x", 1, 300, 200, 100))
                c.execute("INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)", (quote_id, design_id))
                c.execute("""INSERT INTO print_jobs(
                    id,order_id,product_id,variant_id,status,estimated_filament_g)
                    VALUES(?,?,?,?,?,?)""",
                          (job_id, order_id, None, None, "queued", 10))
                c.commit()
            with self.assertRaises(ValueError):
                svc.assign(job_id, printer_id=printer_id)

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
