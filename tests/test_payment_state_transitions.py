import sqlite3
import unittest

from fabos_core.services.payments import PaymentService


class _Database:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

    def connect(self):
        return self.connection


class PaymentStateTransitionTests(unittest.TestCase):
    def setUp(self):
        self.db = _Database()
        self.db.connection.executescript(
            """
            CREATE TABLE payment_transactions(
                id TEXT PRIMARY KEY,
                order_id TEXT,
                invoice_id TEXT,
                customer_id TEXT,
                amount_cents INTEGER,
                currency TEXT,
                provider TEXT,
                provider_payment_id TEXT,
                checkout_url TEXT,
                status TEXT,
                metadata_json TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE TABLE payments(
                id TEXT PRIMARY KEY,
                invoice_id TEXT,
                amount_cents INTEGER,
                method TEXT,
                reference TEXT
            );
            CREATE TABLE orders(id TEXT PRIMARY KEY, status TEXT);
            """
        )
        self.service = PaymentService.__new__(PaymentService)
        self.service.database = self.db

    def _insert(self, payment_id, status):
        self.db.connection.execute(
            "INSERT INTO payment_transactions(id,status) VALUES(?,?)",
            (payment_id, status),
        )
        self.db.connection.commit()

    def test_paid_transaction_ignores_stale_failed_webhook(self):
        self._insert("pay-1", "paid")
        self.service._set_status("pay-1", "failed")
        row = self.db.connection.execute(
            "SELECT status FROM payment_transactions WHERE id='pay-1'"
        ).fetchone()
        self.assertEqual(row["status"], "paid")

    def test_refunded_transaction_ignores_stale_paid_webhook(self):
        self._insert("pay-2", "refunded")
        self.service._set_status("pay-2", "paid")
        row = self.db.connection.execute(
            "SELECT status FROM payment_transactions WHERE id='pay-2'"
        ).fetchone()
        self.assertEqual(row["status"], "refunded")

    def test_paid_transaction_can_enter_partial_refund_state(self):
        self._insert("pay-3", "paid")
        self.service._set_status("pay-3", "partially_refunded")
        row = self.db.connection.execute(
            "SELECT status FROM payment_transactions WHERE id='pay-3'"
        ).fetchone()
        self.assertEqual(row["status"], "partially_refunded")


if __name__ == "__main__":
    unittest.main()
