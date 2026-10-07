"""Regression tests: file uploads require an account.

Product decision: anonymous file uploads are not allowed. The text-only
quote-request form stays public.

- FastAPI POST /api/v1/quote-requests/upload: anonymous -> 401.
- WSGI  POST /api/v1/quote-requests with file_base64: anonymous -> 401;
  without file data the text-only form stays public -> 201.
- Authenticated uploads keep working on both transports.
"""
import base64
import json
import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI
from fabos_core.api import create_app


def _fastapi_client(authenticated=False):
    app = create_app(SimpleNamespace())
    if authenticated:
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "customer-1",
            "account_type": "customer",
        }
    return TestClient(app)


def _multipart_fields():
    return {
        "name": "Jane",
        "email": "jane@example.com",
        "idea": "a widget",
    }


class FastAPIPublicUploadTests(unittest.TestCase):
    def test_anonymous_multipart_upload_is_rejected_401(self):
        client = _fastapi_client(authenticated=False)
        response = client.post(
            "/api/v1/quote-requests/upload",
            files={"file": ("model.stl", b"\x00" * 80, "model/stl")},
            data=_multipart_fields(),
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("authentication", response.json()["detail"].lower())

    def test_authenticated_upload_passes_auth_gate(self):
        # An invalid file still reaches validation (400), proving the request
        # got past the new authentication gate instead of 401.
        client = _fastapi_client(authenticated=True)
        response = client.post(
            "/api/v1/quote-requests/upload",
            files={"file": ("model.stl", b"\x00" * 50, "model/stl")},
            data=_multipart_fields(),
            headers={"Authorization": "Bearer tok"},
        )
        self.assertNotEqual(response.status_code, 401)


class _StubCustomerCommerce:
    def create_public_quote_request(self, name, email, project, file_name="", file_bytes=None):
        if file_bytes is not None:
            raise AssertionError("anonymous file bytes must never reach the service")
        return ({"quote_number": "Q-1"}, [])


class _StubSecurity:
    def context(self, token, permission=None):
        if token == "tok":
            return {"id": "u1", "account_type": "customer"}
        raise PermissionError("Invalid or expired session")


def _wsgi_api():
    core = SimpleNamespace(
        error_log=SimpleNamespace(error=lambda *a, **k: None),
        security=_StubSecurity(),
        customer_commerce=_StubCustomerCommerce(),
    )
    return FabOSAPI(core)


class WSGIQuoteRequestFileTests(unittest.TestCase):
    def _project(self):
        return {"idea": "a widget", "quantity": 1}

    def test_anonymous_base64_file_is_rejected_401(self):
        api = _wsgi_api()
        body = {
            "name": "Jane",
            "email": "jane@example.com",
            "project": self._project(),
            "file_name": "model.stl",
            "file_base64": base64.b64encode(b"\x00" * 80).decode("ascii"),
        }
        result = api.request("POST", "/api/v1/quote-requests", body, {})
        self.assertEqual(result["status"], 401)

    def test_anonymous_text_only_request_stays_public(self):
        api = _wsgi_api()
        body = {
            "name": "Jane",
            "email": "jane@example.com",
            "project": self._project(),
        }
        result = api.request("POST", "/api/v1/quote-requests", body, {})
        self.assertEqual(result["status"], 201)
        self.assertEqual(result["data"]["request_number"], "Q-1")

    def test_authenticated_base64_file_is_accepted(self):
        api = _wsgi_api()

        class _AuthCommerce(_StubCustomerCommerce):
            def create_public_quote_request(self, name, email, project, file_name="", file_bytes=None):
                assert file_bytes, "expected file bytes for authenticated upload"
                return ({"quote_number": "Q-2"}, [])

        api.core.customer_commerce = _AuthCommerce()
        body = {
            "name": "Jane",
            "email": "jane@example.com",
            "project": self._project(),
            "file_name": "model.stl",
            "file_base64": base64.b64encode(b"\x00" * 80).decode("ascii"),
        }
        result = api.request(
            "POST", "/api/v1/quote-requests", body, {"Authorization": "Bearer tok"}
        )
        self.assertEqual(result["status"], 201)
        self.assertEqual(result["data"]["request_number"], "Q-2")


if __name__ == "__main__":
    unittest.main()
