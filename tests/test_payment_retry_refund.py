import sqlite3
import unittest
from unittest.mock import patch

from fabos_core.services.payment_api import _record_refund
from fabos_core.services.payments import PaymentService, StripePaymentProvider


class _Database:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(
            """
            CREATE TABLE payment_transactions(
                id TEXT PRIMARY KEY,
                invoice_id TEXT,
                provider_payment_id TEXT,
                order_id TEXT UNIQUE,
                customer_id TEXT,
                amount_cents INTEGER DEFAULT 0,
                currency TEXT DEFAULT 'USD',
                provider TEXT DEFAULT 'stripe',
                status TEXT DEFAULT 'paid',
                checkout_url TEXT,
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE payments(
                id TEXT PRIMARY KEY,
                invoice_id TEXT,
                amount_cents INTEGER,
                method TEXT,
                reference TEXT,
                notes TEXT
            );
            """
        )

    def connect(self):
        return self.connection


class _Invoices:
    def __init__(self):
        self.reconciled = []

    def reconcile(self, invoice_id):
        self.reconciled.append(invoice_id)


class _Application:
    def __init__(self):
        self.database = _Database()
        self.invoices = _Invoices()


class PaymentRetryRefundTests(unittest.TestCase):
    def test_failed_retry_reuses_transaction_without_duplicate(self):
        database = _Database()
        with database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,order_id,status,provider) VALUES(?,?,?,?)", ("payment-1", "order-1", "failed", "stripe"))
            conn.commit()
        service = object.__new__(PaymentService)
        service.database = database
        payment_id, amount, metadata, ready = service._prepare_transaction({"id": "order-1", "total_cents": 4200}, "customer-1", "invoice-1", "stripe", "customer-web")
        self.assertEqual(payment_id, "payment-1")
        self.assertEqual(amount, 4200)
        self.assertTrue(ready)
        with database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payment_transactions WHERE order_id='order-1'").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT status FROM payment_transactions WHERE id='payment-1'").fetchone()[0], "created")

    def test_active_transaction_is_reused_not_replaced(self):
        database = _Database()
        with database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,order_id,status,provider) VALUES(?,?,?,?)", ("payment-1", "order-1", "pending", "stripe"))
            conn.commit()
        service = object.__new__(PaymentService)
        service.database = database
        payment_id, _, _, ready = service._prepare_transaction({"id": "order-1", "total_cents": 4200}, "customer-1", "invoice-1", "stripe", "customer-web")
        self.assertEqual(payment_id, "payment-1")
        self.assertFalse(ready)

    def test_stripe_request_sets_idempotency_key(self):
        provider = object.__new__(StripePaymentProvider)
        provider.secret_key = "sk_test"

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"id":"cs_test"}'

        with patch("fabos_core.services.payments.urllib.request.urlopen", return_value=Response()) as opened:
            provider._request("/checkout/sessions", {"mode": "payment"}, idempotency_key="payment-1")
        self.assertEqual(opened.call_args.args[0].headers.get("Idempotency-key"), "payment-1")

    def test_partial_refund_sets_partially_refunded(self):
        application = _Application()
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id) VALUES(?,?,?,?)", ("payment-1", "invoice-1", "pi_test", "order-1"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)", ("ledger-1", "invoice-1", 5000, "stripe", "pi_test", "Gateway payment reconciled by FabOS"))
            conn.commit()
        payload = '{"id":"evt_refund_1","type":"refund.created","data":{"object":{"id":"re_test","amount":1800,"payment_intent":"pi_test","status":"succeeded"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["status"], "partially_refunded")

    def test_pending_stripe_refund_is_not_recorded(self):
        application = _Application()
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id) VALUES(?,?,?,?)", ("payment-1", "invoice-1", "pi_test", "order-1"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)", ("ledger-1", "invoice-1", 5000, "stripe", "pi_test", "Gateway payment reconciled by FabOS"))
            conn.commit()
        payload = '{"id":"evt_refund_pending","type":"refund.created","data":{"object":{"id":"re_pending","amount":1800,"payment_intent":"pi_test","status":"pending"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertIsNone(result)
        with application.database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments WHERE amount_cents<0").fetchone()[0], 0)

    def test_charge_refunded_event_does_not_double_count_cumulative_amount(self):
        application = _Application()
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id) VALUES(?,?,?,?)", ("payment-1", "invoice-1", "pi_test", "order-1"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)", ("ledger-1", "invoice-1", 5000, "stripe", "pi_test", "Gateway payment reconciled by FabOS"))
            conn.commit()
        payload = '{"id":"evt_charge_refunded","type":"charge.refunded","data":{"object":{"id":"ch_test","amount":5000,"amount_refunded":1800,"payment_intent":"pi_test"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertIsNone(result)
        with application.database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments WHERE amount_cents<0").fetchone()[0], 0)

    def test_refund_updated_succeeded_is_recorded(self):
        application = _Application()
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id) VALUES(?,?,?,?)", ("payment-1", "invoice-1", "pi_test", "order-1"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)", ("ledger-1", "invoice-1", 5000, "stripe", "pi_test", "Gateway payment reconciled by FabOS"))
            conn.commit()
        payload = '{"id":"evt_refund_updated","type":"refund.updated","data":{"object":{"id":"re_updated","amount":1800,"payment_intent":"pi_test","status":"succeeded"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["amount_cents"], 1800)

    def test_refund_rejects_provider_mismatch(self):
        application = _Application()
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id,provider) VALUES(?,?,?,?,?)",
                         ("payment-1", "invoice-1", "pi_shared", "order-1", "square"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)",
                         ("ledger-1", "invoice-1", 5000, "square", "pi_shared", "Gateway payment reconciled by FabOS"))
            conn.commit()
        payload = '{"id":"evt_refund_mismatch","type":"refund.created","data":{"object":{"id":"re_mismatch","amount":1000,"payment_intent":"pi_shared","status":"succeeded"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "payment_provider_mismatch")
        with application.database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments WHERE amount_cents<0").fetchone()[0], 0)

    def test_refund_rejects_non_refundable_payment_state(self):
        application = _Application()
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id,status) VALUES(?,?,?,?,?)",
                         ("payment-1", "invoice-1", "pi_failed", "order-1", "failed"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)",
                         ("ledger-1", "invoice-1", 5000, "stripe", "pi_failed", "Gateway payment reconciled by FabOS"))
            conn.commit()
        payload = '{"id":"evt_refund_failed","type":"refund.created","data":{"object":{"id":"re_failed","amount":1000,"payment_intent":"pi_failed","status":"succeeded"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "payment_not_refundable")

    def test_full_refund_sets_refunded(self):
        application = _Application()
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id) VALUES(?,?,?,?)", ("payment-1", "invoice-1", "pi_test", "order-1"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)", ("ledger-1", "invoice-1", 5000, "stripe", "pi_test", "Gateway payment reconciled by FabOS"))
            conn.commit()
        payload = '{"id":"evt_refund_1","type":"refund.created","data":{"object":{"id":"re_test","amount":5000,"payment_intent":"pi_test","status":"succeeded"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["status"], "refunded")


if __name__ == "__main__":
    unittest.main()
