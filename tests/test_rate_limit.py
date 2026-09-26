import unittest
from types import SimpleNamespace

from fabos_core.services.rate_limit import request_client_key


class RateLimitClientIdentityTests(unittest.TestCase):
    def test_prefers_edge_sanitized_real_ip(self):
        request = SimpleNamespace(
            headers={"x-real-ip": "203.0.113.10", "x-forwarded-for": "198.51.100.20, 203.0.113.30"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        self.assertEqual(request_client_key(request), "203.0.113.10")

    def test_falls_back_to_forwarded_for_when_real_ip_missing(self):
        request = SimpleNamespace(
            headers={"x-forwarded-for": "198.51.100.20, 203.0.113.30"},
            client=SimpleNamespace(host="127.0.0.1"),
        )
        self.assertEqual(request_client_key(request), "198.51.100.20")

    def test_falls_back_to_socket_peer(self):
        request = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
        self.assertEqual(request_client_key(request), "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
