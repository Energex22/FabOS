import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from fabos_core import cli
from fabos_core.services.auth import AuthService


class ProductionCheckSecurityTests(unittest.TestCase):
    def test_default_owner_password_blocks_production(self):
        previous = dict(os.environ)
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "Backups").mkdir()
                db = root / "fabos.sqlite3"
                conn = sqlite3.connect(db)
                conn.execute("CREATE TABLE users(id TEXT PRIMARY KEY, password_hash TEXT, role TEXT, account_type TEXT, active INTEGER)")
                conn.execute(
                    "INSERT INTO users VALUES(?,?,?,?,?)",
                    ("owner", AuthService(None, None).hash_password("owner-password"), "owner", "administrator", 1),
                )
                conn.commit()
                conn.close()

                os.environ["FABOS_DATA_DIR"] = str(root)
                os.environ["FABOS_PAYMENT_PROVIDER"] = "stripe"
                os.environ["STRIPE_SECRET_KEY"] = "sk_test_example"
                os.environ["STRIPE_SUCCESS_URL"] = "https://fabvex.duckdns.org/orders.html"
                os.environ["STRIPE_CANCEL_URL"] = "https://fabvex.duckdns.org/checkout.html"
                os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_example"
                os.environ["FABOS_API_HOST"] = "127.0.0.1"
                os.environ["FABOS_API_DOCS"] = "false"

                output = io.StringIO()
                with redirect_stdout(output):
                    result = cli._production_check()

                self.assertEqual(result, 1)
                self.assertIn("Bootstrap owner password disabled", output.getvalue())
                self.assertIn("default bootstrap password is still active", output.getvalue())
        finally:
            os.environ.clear()
            os.environ.update(previous)


if __name__ == "__main__":
    unittest.main()
