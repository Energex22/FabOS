import hashlib
import hmac
import json
import time
import unittest

from fabos_core.services.payments import (
    PaymentProviderError,
    _verify_stripe_signature,
    base64_hmac_sha256,
)


class PaymentSecurityTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
