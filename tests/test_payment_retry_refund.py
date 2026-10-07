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
            CREATE TABLE payment_webhook_events(
                id TEXT PRIMARY KEY,
                provider TEXT,
                event_type TEXT,
                payment_id TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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

    def test_refund_webhook_claims_event_id_for_consistent_duplicates(self):
        # L7: the refund early-return claims the provider event id so a
        # duplicate redelivery reports duplicate:true at this level,
        # consistent with _record_refund's ledger-level duplicate report
        # (previously: processed:true/duplicate:false while the ledger said
        # duplicate). Late reconciliation still works because _record_refund
        # runs independently of this claim.
        class _Provider:
            name = "stripe"
            def parse_webhook(self, payload, signature=None):
                return {
                    "event_id": "evt_refund_retry",
                    "event_type": "refund.created",
                    "provider_payment_id": "pi_test",
                    "payment_id": "payment-1",
                    "order_id": "order-1",
                    "invoice_id": "invoice-1",
                    "status": "refunded",
                    "amount_cents": 1800,
                }

        database = _Database()
        service = object.__new__(PaymentService)
        service.database = database
        service._build_provider = lambda name=None: _Provider()
        first = service.handle_webhook(b"{}", "signature", "stripe")
        self.assertTrue(first["processed"])
        self.assertFalse(first["duplicate"])
        with database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payment_webhook_events").fetchone()[0], 1)
        second = service.handle_webhook(b"{}", "signature", "stripe")
        self.assertFalse(second["processed"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["event_id"], "evt_refund_retry")

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

    def _seed_paid_invoice(self, application):
        with application.database.connect() as conn:
            conn.execute("INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id) VALUES(?,?,?,?)", ("payment-1", "invoice-1", "pi_test", "order-1"))
            conn.execute("INSERT INTO payments VALUES(?,?,?,?,?,?)", ("ledger-1", "invoice-1", 5000, "stripe", "pi_test", "Gateway payment reconciled by FabOS"))
            conn.commit()

    def test_duplicate_refund_event_is_idempotent(self):
        application = _Application()
        self._seed_paid_invoice(application)
        payload = '{"id":"evt_refund_dup","type":"refund.created","data":{"object":{"id":"re_dup","amount":1800,"payment_intent":"pi_test","status":"succeeded"}}}'
        first = _record_refund(application, "stripe", payload)
        self.assertTrue(first["recorded"])
        second = _record_refund(application, "stripe", payload)
        self.assertFalse(second["recorded"])
        self.assertTrue(second["duplicate"])
        with application.database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments WHERE amount_cents<0").fetchone()[0], 1)

    def test_cross_event_same_refund_is_idempotent(self):
        # refund.created and refund.updated carry different event_ids but the
        # same refund id; the second must not double-count the ledger.
        application = _Application()
        self._seed_paid_invoice(application)
        created = '{"id":"evt_re_x_created","type":"refund.created","data":{"object":{"id":"re_x","amount":1800,"payment_intent":"pi_test","status":"succeeded"}}}'
        updated = '{"id":"evt_re_x_updated","type":"refund.updated","data":{"object":{"id":"re_x","amount":1800,"payment_intent":"pi_test","status":"succeeded"}}}'
        first = _record_refund(application, "stripe", created)
        self.assertTrue(first["recorded"])
        second = _record_refund(application, "stripe", updated)
        self.assertFalse(second["recorded"])
        self.assertTrue(second["duplicate"])
        with application.database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments WHERE amount_cents<0").fetchone()[0], 1)

    def test_concurrent_claim_loser_is_duplicate(self):
        # Simulate the race loser: the winner's claim is already present when
        # this delivery runs, so it must be treated as a duplicate without
        # touching the ledger.
        application = _Application()
        self._seed_paid_invoice(application)
        with application.database.connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS payment_webhook_events(id TEXT PRIMARY KEY,provider TEXT NOT NULL,event_type TEXT,payment_id TEXT,received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.execute(
                "INSERT INTO payment_webhook_events(id,provider,event_type,payment_id) VALUES(?,?,?,?)",
                ("refund-claim:stripe-refund:re_race", "stripe", "refund.created", "payment-1"),
            )
            conn.commit()
        payload = '{"id":"evt_re_race","type":"refund.created","data":{"object":{"id":"re_race","amount":1800,"payment_intent":"pi_test","status":"succeeded"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertFalse(result["recorded"])
        self.assertTrue(result["duplicate"])
        with application.database.connect() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments WHERE amount_cents<0").fetchone()[0], 0)

    def test_successful_refund_writes_claim_row(self):
        application = _Application()
        self._seed_paid_invoice(application)
        payload = '{"id":"evt_re_claim","type":"refund.created","data":{"object":{"id":"re_claim","amount":1800,"payment_intent":"pi_test","status":"succeeded"}}}'
        result = _record_refund(application, "stripe", payload)
        self.assertTrue(result["recorded"])
        with application.database.connect() as conn:
            row = conn.execute(
                "SELECT provider,event_type,payment_id FROM payment_webhook_events WHERE id=?",
                ("refund-claim:stripe-refund:re_claim",),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["provider"], "stripe")
            self.assertEqual(row["payment_id"], "payment-1")


if __name__ == "__main__":
    unittest.main()
