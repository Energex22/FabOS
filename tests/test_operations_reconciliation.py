import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.operations_hub import OperationsHubService


class OperationsReconciliationTests(unittest.TestCase):
    def test_in_production_order_advances_to_qc_then_ready(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            jid = str(uuid.uuid4())
            qid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
                    (oid, "O-AUTO", "in_production"),
                )
                c.execute(
                    "INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",
                    (jid, oid, "completed"),
                )
                c.commit()

            hub = OperationsHubService(SimpleNamespace(database=db))
            hub.reconcile_workflows()

            with db.connect() as c:
                self.assertEqual(
                    c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0],
                    "qc",
                )
                c.execute(
                    "INSERT INTO qc_inspections(id,order_id,print_job_id,status,checklist_json) "
                    "VALUES(?,?,?,?,?)",
                    (qid, oid, jid, "passed", "[]"),
                )
                c.commit()

            hub.reconcile_workflows()

            with db.connect() as c:
                self.assertEqual(
                    c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0],
                    "ready",
                )

            with db.connect() as c:
                fulfillment = c.execute("SELECT method,status FROM fulfillments WHERE order_id=?", (oid,)).fetchone()
                self.assertIsNotNone(fulfillment)
                self.assertEqual(fulfillment["method"], "pickup")
                self.assertEqual(fulfillment["status"], "pending")

            # A second reconciliation pass must not create another fulfillment row.
            hub.reconcile_workflows()
            with db.connect() as c:
                self.assertEqual(
                    c.execute("SELECT COUNT(*) FROM fulfillments WHERE order_id=?", (oid,)).fetchone()[0],
                    1,
                )


if __name__ == "__main__":
    unittest.main()
