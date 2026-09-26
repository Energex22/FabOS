import os
import tempfile
import unittest
import sqlite3
from pathlib import Path
from unittest.mock import patch

from fabos_core.cli import _production_check


class ProductionPreflightTests(unittest.TestCase):
    def test_preflight_rejects_missing_production_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            env = {
                "FABOS_DATA_DIR": str(Path(td) / "missing"),
                "FABOS_PAYMENT_PROVIDER": "stripe",
                "FABOS_API_HOST": "127.0.0.1",
                "FABOS_API_DOCS": "false",
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(_production_check(), 1)


if __name__ == "__main__":
    unittest.main()


    def test_preflight_accepts_complete_production_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            data_dir = Path(td)
            db_path = data_dir / "fabos.sqlite3"
            with sqlite3.connect(db_path) as conn:
                conn.execute("CREATE TABLE smoke (id INTEGER PRIMARY KEY)")
                conn.execute("PRAGMA user_version = 1")
                conn.commit()
            (data_dir / "Backups").mkdir()
            env = {
                "FABOS_DATA_DIR": str(data_dir),
                "FABOS_PAYMENT_PROVIDER": "stripe",
                "STRIPE_SECRET_KEY": "sk_test_example",
                "STRIPE_MODE": "test",
                "STRIPE_SUCCESS_URL": "https://fabvex.example/orders.html",
                "STRIPE_CANCEL_URL": "https://fabvex.example/checkout.html",
                "STRIPE_WEBHOOK_SECRET": "whsec_example",
                "FABOS_API_HOST": "127.0.0.1",
                "FABOS_API_DOCS": "false",
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(_production_check(), 0)
