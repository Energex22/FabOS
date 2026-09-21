import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.invoices import InvoiceService


class InvoiceOrderTotalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "fabos.db")
        self.db.initialize()
        migrate(self.db)
        self.invoices = InvoiceService(self.db, self.temp.name)
        with self.db.connect() as conn:
            conn.execute(
                """INSERT INTO orders(
                    id,order_number,status,total_cents,tax_cents,shipping_cents
                ) VALUES(?,?,?,?,?,?)""",
                ("order-1", "O-202609-0001", "pending", 10700, 700, 1000),
            )
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    def test_invoice_uses_order_total_without_reapplying_current_tax(self):
        invoice_id, created = self.invoices.create_from_order("order-1")
        self.assertTrue(created)
        with self.db.connect() as conn:
            invoice = conn.execute(
                "SELECT total_cents,subtotal_cents,tax_cents,shipping_cents FROM invoices WHERE id=?",
                (invoice_id,),
            ).fetchone()
        self.assertEqual(dict(invoice), {
            "total_cents": 10700,
            "subtotal_cents": 9000,
            "tax_cents": 700,
            "shipping_cents": 1000,
        })

    def test_zero_value_order_is_not_sent_to_gateway_as_an_invoice(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO orders(id,order_number,status,total_cents) VALUES(?,?,?,?)",
                ("order-free", "O-202609-0002", "pending", 0),
            )
            conn.commit()
        with self.assertRaises(ValueError):
            self.invoices.create_from_order("order-free")


if __name__ == "__main__":
    unittest.main()
