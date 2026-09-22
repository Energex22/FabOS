import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.operations_hub import OperationsHubService


class OperationsReconciliationTests(unittest.TestCase):
    def test_qc_rework_queues_one_replacement_job(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid, jid, qid = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
                          (oid, "O-REWORK", "qc"))
                c.execute("INSERT INTO print_jobs(id,order_id,status,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?)",
                          (jid, oid, "completed", 42, 18))
                c.execute("INSERT INTO qc_inspections(id,order_id,print_job_id,status,checklist_json) VALUES(?,?,?,?,?)",
                          (qid, oid, jid, "rework", "[]"))
                c.commit()
            hub = OperationsHubService(SimpleNamespace(database=db))
            hub.reconcile_workflows()
            with db.connect() as c:
                rows = c.execute(
                    "SELECT id,status,printer_id,spool_id FROM print_jobs WHERE order_id=? ORDER BY created_at",
                    (oid,),
                ).fetchall()
                self.assertEqual(len(rows), 2)
                self.assertEqual(rows[1]["status"], "queued")
                self.assertIsNone(rows[1]["printer_id"])
                self.assertIsNone(rows[1]["spool_id"])
                self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "in_production")
            hub.reconcile_workflows()
            with db.connect() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM print_jobs WHERE order_id=?", (oid,)).fetchone()[0], 2)

    def test_ready_pickup_fulfillment_advances_from_pending(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
                    (oid, "O-PICKUP", "ready"),
                )
                c.execute(
                    "INSERT INTO fulfillments(id,order_id,method,status) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), oid, "pickup", "pending"),
                )
                c.commit()

            hub = OperationsHubService(SimpleNamespace(database=db))
            hub.reconcile_workflows()

            with db.connect() as c:
                fulfillment = c.execute(
                    "SELECT method,status FROM fulfillments WHERE order_id=?", (oid,)
                ).fetchone()
                self.assertEqual(fulfillment["method"], "pickup")
                self.assertEqual(fulfillment["status"], "ready_for_pickup")

            hub.reconcile_workflows()
            with db.connect() as c:
                self.assertEqual(
                    c.execute("SELECT COUNT(*) FROM fulfillments WHERE order_id=?", (oid,)).fetchone()[0],
                    1,
                )

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
                self.assertEqual(fulfillment["status"], "ready_for_pickup")

            # A second reconciliation pass must not create another fulfillment row.
            hub.reconcile_workflows()
            with db.connect() as c:
                self.assertEqual(
                    c.execute("SELECT COUNT(*) FROM fulfillments WHERE order_id=?", (oid,)).fetchone()[0],
                    1,
                )


if __name__ == "__main__":
    unittest.main()
