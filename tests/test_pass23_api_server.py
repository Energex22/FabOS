import io
import unittest

from fabos_api.server import _application_with_cors


class _Security:
    def context(self, token, permission=None):
        if token != "token":
            raise PermissionError("Invalid or expired session")
        return {"id": "u1"}


class _Core:
    security = _Security()
    error_log = type("Log", (), {"error": lambda self, *args: None})()


class Pass23APIServerTests(unittest.TestCase):
    def test_cors_health_response(self):
        captured = {}
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/health", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
            "HTTP_AUTHORIZATION": "", "HTTP_USER_AGENT": "test", "REMOTE_ADDR": "127.0.0.1",
        }

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        payload = b"".join(_application_with_cors(_Core())(environ, start_response))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(captured["headers"]["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertIn(b'"ok": true', payload)

    def test_options_preflight(self):
        captured = {}
        environ = {
            "REQUEST_METHOD": "OPTIONS", "PATH_INFO": "/api/v1/products", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
        }

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        payload = b"".join(_application_with_cors(_Core())(environ, start_response))
        self.assertEqual(captured["status"], "204 No Content")
        self.assertEqual(captured["headers"]["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertEqual(payload, b"")


if __name__ == "__main__":
    unittest.main()
