import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.fulfillment import FulfillmentService


class FulfillmentLifecycleTests(unittest.TestCase):
    def test_shipping_fulfillment_supports_packed_then_shipped(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
                    (oid, "O-SHIP", "ready"),
                )
                c.commit()

            service = FulfillmentService(db)
            fid = service.ensure(oid, "shipping")
            service.save(oid, "shipping", "packed")
            with db.connect() as c:
                row = c.execute("SELECT status,method FROM fulfillments WHERE id=?", (fid,)).fetchone()
                self.assertEqual(row["status"], "packed")
                self.assertEqual(row["method"], "shipping")
                self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "ready")

            service.save(oid, "shipping", "shipped", carrier="Carrier", tracking="TRACK-1")
            with db.connect() as c:
                row = c.execute("SELECT status,tracking_number,shipped_at FROM fulfillments WHERE id=?", (fid,)).fetchone()
                self.assertEqual(row["status"], "shipped")
                self.assertEqual(row["tracking_number"], "TRACK-1")
                self.assertIsNotNone(row["shipped_at"])
                self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "shipped")


if __name__ == "__main__":
    unittest.main()
