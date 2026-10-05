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


    def test_fulfillment_cannot_advance_before_qc_ready(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
                    (oid, "O-NOTREADY", "qc"),
                )
                c.commit()
            service = FulfillmentService(db)
            with self.assertRaises(ValueError):
                service.save(oid, "shipping", "packed")

    def test_fulfillment_cannot_move_backwards(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)", (oid, "O-BACK", "ready"))
                c.commit()
            service = FulfillmentService(db)
            service.save(oid, "shipping", "shipped")
            with self.assertRaises(ValueError):
                service.save(oid, "shipping", "packed")

    def test_shipping_cost_cannot_change_during_active_payment(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            iid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO orders(id,order_number,status,total_cents,tax_cents,shipping_cents) VALUES(?,?,?,?,?,?)", (oid, "O-PAY", "pending", 1100, 0, 100))
                c.execute("INSERT INTO invoices(id,invoice_number,order_id,status,total_cents,paid_cents,due_at,subtotal_cents,tax_cents,shipping_cents,discount_cents) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (iid, "INV-TEST", oid, "open", 1100, 0, "2099-01-01", 1000, 0, 100, 0))
                c.execute("CREATE TABLE IF NOT EXISTS payment_transactions(id TEXT PRIMARY KEY, invoice_id TEXT, order_id TEXT, provider TEXT, status TEXT, amount_cents INTEGER)")
                c.execute("INSERT INTO payment_transactions(id,invoice_id,order_id,provider,status,amount_cents) VALUES(?,?,?,?,?,?)", (str(uuid.uuid4()), iid, oid, "stripe", "pending", 1100))
                c.commit()
            service = FulfillmentService(db)
            with self.assertRaises(ValueError):
                service.save(oid, "shipping", "packed", shipping_cost_cents=250)


    def test_terminal_fulfillment_cannot_bypass_production_completion_gates(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            jid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
                    (oid, "O-QC-GATE", "ready"),
                )
                c.execute(
                    "INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",
                    (jid, oid, "queued"),
                )
                c.commit()

            service = FulfillmentService(db)
            service.save(oid, "shipping", "delivered")
            with db.connect() as c:
                self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "shipped")

    def test_payment_can_finish_order_after_fulfillment_was_already_completed(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            jid = str(uuid.uuid4())
            qid = str(uuid.uuid4())
            iid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",
                    (oid, "O-PAY-AFTER-FULFILLMENT", "ready", 1000),
                )
                c.execute(
                    "INSERT INTO invoices(id,invoice_number,order_id,status,subtotal_cents,tax_cents,shipping_cents,discount_cents,total_cents,paid_cents) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (iid, "INV-PAY-AFTER-FULFILLMENT", oid, "open", 1000, 0, 0, 0, 1000, 0),
                )
                c.execute(
                    "INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",
                    (jid, oid, "completed"),
                )
                c.execute(
                    "INSERT INTO qc_inspections(id,order_id,print_job_id,status) VALUES(?,?,?,'passed')",
                    (qid, oid, jid),
                )
                c.commit()

            service = FulfillmentService(db)
            service.save(oid, "shipping", "delivered")

            with db.connect() as c:
                self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "shipped")

            from fabos_core.services.invoices import InvoiceService
            InvoiceService(db, Path(td) / "data").record_payment(
                iid, 1000, method="test", reference="pay-after-fulfillment"
            )

            with db.connect() as c:
                self.assertEqual(c.execute("SELECT status FROM invoices WHERE id=?", (iid,)).fetchone()[0], "paid")
                self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "completed")

    def test_terminal_fulfillment_can_complete_when_all_gates_are_met(self):
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
                    (oid, "O-COMPLETE", "ready"),
                )
                c.execute(
                    "INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",
                    (jid, oid, "completed"),
                )
                c.execute(
                    "INSERT INTO qc_inspections(id,order_id,print_job_id,status) VALUES(?,?,?,'passed')",
                    (qid, oid, jid),
                )
                c.commit()

            FulfillmentService(db).save(oid, "shipping", "delivered")
            with db.connect() as c:
                self.assertEqual(c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()[0], "completed")

    def test_fulfillment_method_cannot_use_the_other_method_statuses(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,0)",
                    (oid, "O-METHOD", "ready"),
                )
                c.commit()

            service = FulfillmentService(db)
            with self.assertRaises(ValueError):
                service.save(oid, "pickup", "shipped")
            with self.assertRaises(ValueError):
                service.save(oid, "shipping", "picked_up")


if __name__ == "__main__":
    unittest.main()
