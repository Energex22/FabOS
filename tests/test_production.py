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

if __name__ == "__main__":
    unittest.main()
