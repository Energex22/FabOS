"""Regression tests for the second-pass hardening fixes.

Covers: WSGI proof-comment length cap (item 1), CAD reference-image
magic-byte sniffing (item 3), and X-Forwarded-For trusted-proxy handling in
rate-limit keying (item 4). The refund-claim race (item 2) is covered in
tests/test_payment_retry_refund.py.
"""
import unittest
from types import SimpleNamespace

from fabos_api import FabOSAPI
from fabos_api.app import _rate_limit_client_ip
from fabos_core.api import _sniff_reference_image_type


class _Security:
    def context(self, token, permission=None):
        if token == "customer-token":
            return {"id": "customer-user", "account_type": "customer"}
        raise PermissionError("Invalid or expired session")


class _Proofs:
    def __init__(self):
        self.rows = {}

    def approve(self, user_id, proof_id, comment=""):
        if proof_id not in self.rows:
            raise KeyError("Design proof not found.")
        return {"id": proof_id, "status": "approved"}

    def request_changes(self, user_id, proof_id, comment):
        if proof_id not in self.rows:
            raise KeyError("Design proof not found.")
        return {"id": proof_id, "status": "changes_requested"}

    def _public(self, row):
        return {"id": row["id"], "status": row.get("status", "approved")}


class _Log:
    def error(self, title, exc):
        pass


class WsgiProofCommentCapTests(unittest.TestCase):
    def setUp(self):
        self.core = SimpleNamespace(
            security=_Security(),
            design_proofs=_Proofs(),
            error_log=_Log(),
        )
        self.api = FabOSAPI(self.core)
        self.customer = {"Authorization": "Bearer customer-token"}
        self.core.design_proofs.rows["p1"] = {"id": "p1", "status": "sent"}

    def test_approve_rejects_overlong_comment(self):
        result = self.api.request(
            "POST", "/api/v1/customer/proofs/p1/approve",
            {"comment": "x" * 4001}, self.customer,
        )
        self.assertEqual(result["status"], 400)

    def test_approve_accepts_comment_at_cap(self):
        result = self.api.request(
            "POST", "/api/v1/customer/proofs/p1/approve",
            {"comment": "x" * 4000}, self.customer,
        )
        self.assertEqual(result["status"], 200)

    def test_request_changes_rejects_overlong_comment(self):
        result = self.api.request(
            "POST", "/api/v1/customer/proofs/p1/request-changes",
            {"comment": "x" * 4001}, self.customer,
        )
        self.assertEqual(result["status"], 400)

    def test_request_changes_accepts_comment_at_cap(self):
        result = self.api.request(
            "POST", "/api/v1/customer/proofs/p1/request-changes",
            {"comment": "needs work"}, self.customer,
        )
        self.assertEqual(result["status"], 200)


class ReferenceImageSniffTests(unittest.TestCase):
    def test_png_magic(self):
        self.assertEqual(
            _sniff_reference_image_type(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100),
            "image/png",
        )

    def test_jpeg_magic(self):
        self.assertEqual(
            _sniff_reference_image_type(b"\xff\xd8\xff\xe0" + b"\x00" * 100),
            "image/jpeg",
        )

    def test_gif_magic_detected(self):
        self.assertEqual(_sniff_reference_image_type(b"GIF89a" + b"\x00" * 100), "image/gif")
        self.assertEqual(_sniff_reference_image_type(b"GIF87a" + b"\x00" * 100), "image/gif")

    def test_webp_magic(self):
        self.assertEqual(
            _sniff_reference_image_type(b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 100),
            "image/webp",
        )

    def test_spoofed_content_is_not_trusted(self):
        # A non-image (or wrong image) must not sniff as the claimed type.
        self.assertIsNone(_sniff_reference_image_type(b"not an image at all"))
        self.assertIsNone(_sniff_reference_image_type(b""))
        self.assertNotEqual(
            _sniff_reference_image_type(b"\xff\xd8\xff\xe0" + b"\x00" * 10),
            "image/png",
        )


class RateLimitClientIpTests(unittest.TestCase):
    def test_trusts_xff_from_loopback_proxy(self):
        headers = {"X-Direct-Peer": "127.0.0.1", "X-Forwarded-For": "203.0.113.7, 10.0.0.1"}
        self.assertEqual(_rate_limit_client_ip(headers), "203.0.113.7")

    def test_trusts_xff_from_ipv6_loopback(self):
        headers = {"X-Direct-Peer": "::1", "X-Forwarded-For": "203.0.113.8"}
        self.assertEqual(_rate_limit_client_ip(headers), "203.0.113.8")

    def test_ignores_spoofed_xff_from_remote_peer(self):
        headers = {"X-Direct-Peer": "198.51.100.9", "X-Forwarded-For": "203.0.113.7"}
        self.assertEqual(_rate_limit_client_ip(headers), "198.51.100.9")

    def test_falls_back_to_direct_peer_without_xff(self):
        self.assertEqual(_rate_limit_client_ip({"X-Direct-Peer": "198.51.100.9"}), "198.51.100.9")

    def test_unknown_when_nothing_available(self):
        self.assertEqual(_rate_limit_client_ip({}), "unknown")
        self.assertEqual(_rate_limit_client_ip(None), "unknown")


if __name__ == "__main__":
    unittest.main()
