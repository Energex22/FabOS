import io
import os
import unittest

from fastapi.testclient import TestClient

from fabos_api.server import _application_with_cors


class _Security:
    def context(self, token, permission=None):
        if token != "token":
            raise PermissionError("Invalid or expired session")
        return {"id": "u1"}


class _Auth:
    def __init__(self):
        self.calls = 0

    def login(self, identifier, password):
        self.calls += 1
        return None


class _Core:
    def __init__(self):
        self.security = _Security()
        self.auth = _Auth()
        self.error_log = type("Log", (), {"error": lambda self, *args: None})()


class Pass23APIServerTests(unittest.TestCase):
    def test_cors_health_response(self):
        os.environ["FABOS_CORS_ORIGINS"] = "http://localhost:5173"
        self.addCleanup(lambda: os.environ.pop("FABOS_CORS_ORIGINS", None))
        captured = {}
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/health", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
            "HTTP_AUTHORIZATION": "", "HTTP_USER_AGENT": "test", "REMOTE_ADDR": "127.0.0.1", "HTTP_ORIGIN": "http://localhost:5173",
        }

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        payload = b"".join(_application_with_cors(_Core())(environ, start_response))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(captured["headers"]["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertIn(b'"ok": true', payload)

    def test_production_server_uses_canonical_cors_setting(self):
        from fabos_api.server import _application_with_cors

        core = _Core()
        previous = os.environ.get("FABOS_CORS_ORIGINS")
        try:
            os.environ["FABOS_CORS_ORIGINS"] = "https://shop.example"
            captured = {}
            environ = {
                "REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/health", "QUERY_STRING": "",
                "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""), "HTTP_ORIGIN": "https://shop.example",
            }
            def start_response(status, headers):
                captured["headers"] = dict(headers)
            b"".join(_application_with_cors(core)(environ, start_response))
            self.assertEqual(captured["headers"]["Access-Control-Allow-Origin"], "https://shop.example")
        finally:
            if previous is None:
                os.environ.pop("FABOS_CORS_ORIGINS", None)
            else:
                os.environ["FABOS_CORS_ORIGINS"] = previous

    def test_team_login_is_rate_limited_independently(self):
        from fabos_core.api import create_app

        core = _Core()
        client = TestClient(create_app(core))
        for _ in range(10):
            response = client.post("/api/v1/auth/team-login", json={"identifier": "admin", "password": "wrong"})
            self.assertEqual(response.status_code, 401)
        response = client.post("/api/v1/auth/team-login", json={"identifier": "admin", "password": "wrong"})
        self.assertEqual(response.status_code, 429)
        self.assertIn("Retry-After", response.headers)
        self.assertEqual(core.auth.calls, 10)

    def test_customer_and_team_login_limiters_are_independent(self):
        from fabos_core.api import create_app

        core = _Core()
        client = TestClient(create_app(core))
        for _ in range(10):
            response = client.post("/api/v1/auth/login", json={"identifier": "customer", "password": "wrong"})
            self.assertEqual(response.status_code, 401)
        response = client.post("/api/v1/auth/login", json={"identifier": "customer", "password": "wrong"})
        self.assertEqual(response.status_code, 429)
        response = client.post("/api/v1/auth/team-login", json={"identifier": "admin", "password": "wrong"})
        self.assertEqual(response.status_code, 401)

    def test_options_preflight(self):
        os.environ["FABOS_CORS_ORIGINS"] = "http://localhost:5173"
        self.addCleanup(lambda: os.environ.pop("FABOS_CORS_ORIGINS", None))
        captured = {}
        environ = {
            "REQUEST_METHOD": "OPTIONS", "PATH_INFO": "/api/v1/products", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""), "HTTP_ORIGIN": "http://localhost:5173",
        }

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        payload = b"".join(_application_with_cors(_Core())(environ, start_response))
        self.assertEqual(captured["status"], "204 No Content")
        self.assertEqual(captured["headers"]["Access-Control-Allow-Origin"], "http://localhost:5173")
        self.assertEqual(payload, b"")

    def test_disallowed_cors_origin_is_not_reflected(self):
        captured = {}
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/health", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
            "HTTP_ORIGIN": "https://evil.example",
        }
        def start_response(status, headers):
            captured["headers"] = dict(headers)
        b"".join(_application_with_cors(_Core())(environ, start_response))
        self.assertNotIn("Access-Control-Allow-Origin", captured["headers"])

    def test_disallowed_preflight_is_rejected(self):
        captured = {}
        environ = {
            "REQUEST_METHOD": "OPTIONS", "PATH_INFO": "/api/v1/health", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
            "HTTP_ORIGIN": "https://evil.example",
        }
        def start_response(status, headers):
            captured["status"] = status
        b"".join(_application_with_cors(_Core())(environ, start_response))
        self.assertEqual(captured["status"], "403 Forbidden")

    def test_wsgi_team_login_is_rate_limited(self):
        from fabos_api.app import FabOSAPI
        core = _Core()
        api = FabOSAPI(core)
        headers = {"X-Forwarded-For": "203.0.113.10"}
        for _ in range(10):
            self.assertEqual(api.request("POST", "/api/v1/auth/team-login", {"identifier": "admin", "password": "wrong"}, headers)["status"], 401)
        self.assertEqual(api.request("POST", "/api/v1/auth/team-login", {"identifier": "admin", "password": "wrong"}, headers)["status"], 429)
        self.assertEqual(core.auth.calls, 10)


if __name__ == "__main__":
    unittest.main()
