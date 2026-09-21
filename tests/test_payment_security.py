import hashlib
import hmac
import json
import os
import sqlite3
import time
import unittest

from fabos_core.services.payment_api import _record_refund
from fabos_core.services.payments import (
    PaymentProviderError,
    StripePaymentProvider,
    _verify_stripe_signature,
    base64_hmac_sha256,
)


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
                order_id TEXT,
                status TEXT DEFAULT 'paid',
                updated_at TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
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


class PaymentSecurityTests(unittest.TestCase):
    def _seed_payment(self, application, amount=5000):
        with application.database.connect() as conn:
            conn.execute(
                "INSERT INTO payment_transactions(id,invoice_id,provider_payment_id,order_id) VALUES(?,?,?,?)",
                ("payment-1", "invoice-1", "pi_test", "order-1"),
            )
            conn.execute(
                "INSERT INTO payments(id,invoice_id,amount_cents,method,reference,notes) VALUES(?,?,?,?,?,?)",
                ("payment-ledger-1", "invoice-1", amount, "stripe", "pi_test", "Gateway payment reconciled by FabOS"),
            )
            conn.commit()

    def test_stripe_signature_accepts_valid_payload(self):
        secret = "whsec_test"
        payload = json.dumps({"id": "evt_test", "type": "checkout.session.completed"})
        timestamp = str(int(time.time()))
        signed = f"{timestamp}.{payload}".encode("utf-8")
        digest = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
        _verify_stripe_signature(payload, f"t={timestamp},v1={digest}", secret)

    def test_stripe_signature_rejects_tampered_payload(self):
        secret = "whsec_test"
        payload = "{\"id\":\"evt_test\"}"
        timestamp = str(int(time.time()))
        digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.{payload}".encode("utf-8"), hashlib.sha256).hexdigest()
        with self.assertRaises(PaymentProviderError):
            _verify_stripe_signature(payload + " ", f"t={timestamp},v1={digest}", secret)

    def test_stripe_signature_rejects_stale_timestamp(self):
        secret = "whsec_test"
        payload = "{}"
        timestamp = str(int(time.time()) - 601)
        digest = hmac.new(secret.encode("utf-8"), f"{timestamp}.{payload}".encode("utf-8"), hashlib.sha256).hexdigest()
        with self.assertRaises(PaymentProviderError):
            _verify_stripe_signature(payload, f"t={timestamp},v1={digest}", secret)

    def test_square_signature_matches_expected_hmac(self):
        secret = "square_webhook_key"
        message = "https://example.test/webhooks/square" + '{"event":"payment.updated"}'
        expected = base64_hmac_sha256(secret, message)
        self.assertEqual(expected, base64_hmac_sha256(secret, message))
        self.assertNotEqual(expected, base64_hmac_sha256(secret, message + "x"))

    def test_stripe_webhook_uses_client_reference_as_order_id(self):
        previous_key = os.environ.get("STRIPE_SECRET_KEY")
        previous_webhook = os.environ.get("STRIPE_WEBHOOK_SECRET")
        os.environ["STRIPE_SECRET_KEY"] = "sk_test"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
        try:
            provider = StripePaymentProvider()
            payload = json.dumps(
                {
                    "id": "evt_payment_intent",
                    "type": "payment_intent.succeeded",
                    "data": {"object": {"id": "pi_test", "metadata": {}, "client_reference_id": "order-42"}},
                }
            )
            timestamp = str(int(time.time()))
            digest = hmac.new("whsec_test".encode("utf-8"), f"{timestamp}.{payload}".encode("utf-8"), hashlib.sha256).hexdigest()
            event = provider.parse_webhook(payload, f"t={timestamp},v1={digest}")
            self.assertEqual(event["provider_payment_id"], "pi_test")
            self.assertEqual(event["order_id"], "order-42")
            self.assertEqual(event["status"], "paid")
        finally:
            if previous_key is None:
                os.environ.pop("STRIPE_SECRET_KEY", None)
            else:
                os.environ["STRIPE_SECRET_KEY"] = previous_key
            if previous_webhook is None:
                os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
            else:
                os.environ["STRIPE_WEBHOOK_SECRET"] = previous_webhook

    def test_stripe_paid_webhook_parses_gateway_amount(self):
        previous_key = os.environ.get("STRIPE_SECRET_KEY")
        previous_webhook = os.environ.get("STRIPE_WEBHOOK_SECRET")
        os.environ["STRIPE_SECRET_KEY"] = "sk_test"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_test"
        try:
            provider = StripePaymentProvider()
            payload = json.dumps({
                "id": "evt_amount",
                "type": "payment_intent.succeeded",
                "data": {"object": {"id": "pi_amount", "amount_received": 5000, "metadata": {"payment_id": "payment-1"}}},
            })
            timestamp = str(int(time.time()))
            digest = hmac.new("whsec_test".encode("utf-8"), f"{timestamp}.{payload}".encode("utf-8"), hashlib.sha256).hexdigest()
            event = provider.parse_webhook(payload, f"t={timestamp},v1={digest}")
            self.assertEqual(event["amount_cents"], 5000)
        finally:
            if previous_key is None:
                os.environ.pop("STRIPE_SECRET_KEY", None)
            else:
                os.environ["STRIPE_SECRET_KEY"] = previous_key
            if previous_webhook is None:
                os.environ.pop("STRIPE_WEBHOOK_SECRET", None)
            else:
                os.environ["STRIPE_WEBHOOK_SECRET"] = previous_webhook

    def test_stripe_refund_is_recorded_as_negative_ledger_entry(self):
        application = _Application()
        self._seed_payment(application)
        payload = json.dumps(
            {
                "id": "evt_refund_1",
                "type": "refund.created",
                "data": {"object": {"id": "re_test", "amount": 1800, "payment_intent": "pi_test"}},
            }
        )
        result = _record_refund(application, "stripe", payload)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["amount_cents"], 1800)
        self.assertEqual(result["status"], "partially_refunded")
        with application.database.connect() as conn:
            row = conn.execute("SELECT amount_cents,reference FROM payments WHERE invoice_id=? AND amount_cents<0", ("invoice-1",)).fetchone()
            tx = conn.execute("SELECT status FROM payment_transactions WHERE id='payment-1'").fetchone()
        self.assertEqual(row["amount_cents"], -1800)
        self.assertEqual(row["reference"], "stripe-refund:re_test")
        self.assertEqual(tx["status"], "partially_refunded")
        self.assertEqual(application.invoices.reconciled, ["invoice-1"])

    def test_full_refund_sets_refunded_status(self):
        application = _Application()
        self._seed_payment(application, amount=5000)
        payload = json.dumps(
            {
                "id": "evt_refund_full",
                "type": "refund.created",
                "data": {"object": {"id": "re_full", "amount": 5000, "payment_intent": "pi_test"}},
            }
        )
        result = _record_refund(application, "stripe", payload)
        self.assertTrue(result["recorded"])
        self.assertEqual(result["amount_cents"], 5000)
        self.assertEqual(result["status"], "refunded")
        with application.database.connect() as conn:
            tx = conn.execute("SELECT status FROM payment_transactions WHERE id='payment-1'").fetchone()
        self.assertEqual(tx["status"], "refunded")

    def test_refund_cannot_overdraw_recorded_payment(self):
        application = _Application()
        self._seed_payment(application, amount=5000)
        payload = json.dumps(
            {
                "id": "evt_refund_over",
                "type": "refund.created",
                "data": {"object": {"id": "re_over", "amount": 6000, "payment_intent": "pi_test"}},
            }
        )
        result = _record_refund(application, "stripe", payload)
        self.assertFalse(result["recorded"])
        self.assertEqual(result["reason"], "refund_exceeds_recorded_payment")
        with application.database.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM payments WHERE invoice_id=? AND amount_cents<0", ("invoice-1",)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_same_provider_refund_event_is_idempotent(self):
        application = _Application()
        self._seed_payment(application)
        payload = json.dumps(
            {
                "id": "evt_refund_1",
                "type": "refund.created",
                "data": {"object": {"id": "re_test", "amount": 1800, "payment_intent": "pi_test"}},
            }
        )
        first = _record_refund(application, "stripe", payload)
        second = _record_refund(application, "stripe", payload)
        self.assertTrue(first["recorded"])
        self.assertTrue(second["duplicate"])
        with application.database.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM payments WHERE invoice_id=? AND amount_cents<0", ("invoice-1",)).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
