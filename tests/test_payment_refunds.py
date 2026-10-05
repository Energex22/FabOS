import tempfile
import unittest
import uuid
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.payments import PaymentService


class PaymentRefundTests(unittest.TestCase):
    def test_refund_reduces_invoice_paid_balance(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            iid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,1000)",
                    (oid, "O-REFUND", "confirmed"),
                )
                c.execute(
                    """INSERT INTO invoices(
                        id,invoice_number,order_id,status,total_cents,paid_cents,
                        due_at,subtotal_cents,tax_cents,shipping_cents,discount_cents
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (iid, "INV-REFUND", oid, "open", 1000, 0,
                     "2099-01-01", 1000, 0, 0, 0),
                )
                c.commit()

            invoices = InvoiceService(db, Path(td) / "data")
            invoices.record_payment(iid, 1000, method="test", reference="pay-1")
            invoices.record_refund(iid, 1000, reference="refund-1")

            with db.connect() as c:
                invoice = c.execute(
                    "SELECT paid_cents,status FROM invoices WHERE id=?", (iid,)
                ).fetchone()
                self.assertEqual(invoice["paid_cents"], 0)
                self.assertEqual(invoice["status"], "open")
                payments = c.execute(
                    "SELECT amount_cents,method,reference FROM payments WHERE invoice_id=? ORDER BY rowid",
                    (iid,),
                ).fetchall()
                self.assertEqual([p["amount_cents"] for p in payments], [1000, -1000])
                self.assertEqual(payments[-1]["method"], "refund")

    def test_gateway_partial_refunds_use_each_refund_amount(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            iid = str(uuid.uuid4())
            pid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,1000)",
                    (oid, "O-PARTIAL-REFUND", "confirmed"),
                )
                c.execute(
                    """INSERT INTO invoices(
                        id,invoice_number,order_id,status,total_cents,paid_cents,
                        due_at,subtotal_cents,tax_cents,shipping_cents,discount_cents
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (iid, "INV-PARTIAL-REFUND", oid, "paid", 1000, 1000,
                     "2099-01-01", 1000, 0, 0, 0),
                )
                c.execute(
                    """INSERT INTO payment_transactions(
                        id,order_id,invoice_id,amount_cents,provider,status
                    ) VALUES(?,?,?,?,?,'paid')""",
                    (pid, oid, iid, 1000, "stripe"),
                )
                c.commit()

            invoices = InvoiceService(db, Path(td) / "data")
            invoices.record_payment(iid, 1000, method="stripe", reference="gateway-pay")

            service = object.__new__(PaymentService)
            service.database = db
            service.invoices = invoices
            service._set_status(pid, "partially_refunded", provider_payment_id="refund-300", refund_amount_cents=300)
            service._set_status(pid, "partially_refunded", provider_payment_id="refund-700", refund_amount_cents=700)

            with db.connect() as c:
                invoice = c.execute(
                    "SELECT paid_cents,status FROM invoices WHERE id=?", (iid,)
                ).fetchone()
                self.assertEqual(invoice["paid_cents"], 0)
                self.assertEqual(invoice["status"], "open")
                refunds = c.execute(
                    "SELECT amount_cents,reference FROM payments WHERE invoice_id=? AND method='refund' ORDER BY rowid",
                    (iid,),
                ).fetchall()
                self.assertEqual([r["amount_cents"] for r in refunds], [-300, -700])

    def test_gateway_refund_status_reconciles_the_invoice_once(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(Path(td) / "fabos.sqlite3")
            db.initialize()
            migrate(db)
            oid = str(uuid.uuid4())
            iid = str(uuid.uuid4())
            pid = str(uuid.uuid4())
            with db.connect() as c:
                c.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,1000)",
                    (oid, "O-GATEWAY-REFUND", "confirmed"),
                )
                c.execute(
                    """INSERT INTO invoices(
                        id,invoice_number,order_id,status,total_cents,paid_cents,
                        due_at,subtotal_cents,tax_cents,shipping_cents,discount_cents
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                    (iid, "INV-GATEWAY-REFUND", oid, "open", 1000, 0,
                     "2099-01-01", 1000, 0, 0, 0),
                )
                c.execute(
                    """INSERT INTO payment_transactions(
                        id,order_id,invoice_id,amount_cents,provider,status
                    ) VALUES(?,?,?,?,?,'paid')""",
                    (pid, oid, iid, 1000, "stripe"),
                )
                c.commit()

            invoices = InvoiceService(db, Path(td) / "data")
            invoices.record_payment(iid, 1000, method="stripe", reference="gateway-pay")

            service = object.__new__(PaymentService)
            service.database = db
            service.invoices = invoices
            service._set_status(pid, "refunded", provider_payment_id="gateway-refund-1")
            service._set_status(pid, "refunded", provider_payment_id="gateway-refund-1")

            with db.connect() as c:
                invoice = c.execute(
                    "SELECT paid_cents,status FROM invoices WHERE id=?", (iid,)
                ).fetchone()
                self.assertEqual(invoice["paid_cents"], 0)
                self.assertEqual(invoice["status"], "open")
                self.assertEqual(
                    c.execute(
                        "SELECT COUNT(*) FROM payments WHERE invoice_id=? AND method='refund'",
                        (iid,),
                    ).fetchone()[0],
                    1,
                )
                self.assertEqual(
                    c.execute(
                        "SELECT status FROM payment_transactions WHERE id=?", (pid,)
                    ).fetchone()[0],
                    "refunded",
                )


if __name__ == "__main__":
    unittest.main()
