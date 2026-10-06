import unittest
from types import SimpleNamespace

from fastapi.testclient import TestClient

from fabos_core.api import create_app


class CustomerQuoteUploadRegressionTests(unittest.TestCase):
    """H3 regression: an invalid model upload must surface the validation 400.

    create_customer_quote_with_file used to reference ``success`` in its
    ``finally`` block before it was ever assigned, so any validation failure
    raised UnboundLocalError (HTTP 500) instead of the intended 400 and
    skipped temp-file/orphan cleanup.
    """

    def _client(self):
        app = create_app(SimpleNamespace())
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "customer-1",
            "account_type": "customer",
        }
        return TestClient(app)

    def test_invalid_stl_upload_returns_400_not_500(self):
        client = self._client()
        response = client.post(
            "/api/v1/customer/quotes/upload",
            files={"file": ("model.stl", b"\x00" * 50, "model/stl")},
            data={"idea": "a widget"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid binary STL model", response.json()["detail"])

    def test_unsupported_extension_returns_415(self):
        client = self._client()
        response = client.post(
            "/api/v1/customer/quotes/upload",
            files={"file": ("model.exe", b"MZ", "application/octet-stream")},
            data={"idea": "a widget"},
        )
        self.assertEqual(response.status_code, 415)


if __name__ == "__main__":
    unittest.main()
