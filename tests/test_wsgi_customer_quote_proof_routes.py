"""WSGI quote/proof customer routes: parity with the FastAPI customer surface.

The WSGI server previously did not serve the customer quote/proof routes
(accept/decline quotes, list/get proofs, approve/request-changes, proof file),
so the frontend quote/proof pages 404'd on WSGI deployments. These tests pin
the new routes' behavior against the FastAPI semantics in fabos_core/api.py
and fabos_core/services/design_proofs_api.py.
"""
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fabos_api import FabOSAPI, create_wsgi_app


class _Security:
    def context(self, token, permission=None):
        if token == "customer-token":
            return {"id": "customer-user", "account_type": "customer"}
        if token == "employee-token":
            return {"id": "employee-user", "account_type": "employee"}
        raise PermissionError("Invalid or expired session")


class _Quotes:
    def __init__(self):
        self.statuses = {}
        self.converted = []

    def get_for_user(self, user_id, quote_id):
        row = self.statuses.get(quote_id)
        if row is None:
            raise KeyError("Quote not found")
        return row, []

    def set_status(self, quote_id, status):
        self.statuses[quote_id]["status"] = status

    def convert_to_order(self, quote_id):
        self.converted.append(quote_id)
        return "order-%s" % quote_id


class _Proofs:
    def __init__(self):
        self.rows = {}
        self.actions = []

    def list_for_customer(self, user_id):
        return [{"id": proof_id, "status": row.get("status", "sent")} for proof_id, row in self.rows.items()]

    def get_for_customer(self, user_id, proof_id):
        if proof_id not in self.rows:
            raise KeyError("Design proof not found.")
        return {"id": proof_id, "status": self.rows[proof_id].get("status", "sent")}

    def _row(self, proof_id):
        return self.rows[proof_id]

    def _public(self, row):
        return {"id": row["id"], "status": row.get("status", "approved")}

    def approve(self, user_id, proof_id, comment=""):
        if proof_id not in self.rows:
            raise KeyError("Design proof not found.")
        if self.rows[proof_id].get("status") != "sent":
            raise ValueError("This proof is no longer awaiting customer review.")
        self.actions.append(("approve", proof_id, comment))
        return {"id": proof_id, "status": "approved"}

    def request_changes(self, user_id, proof_id, comment):
        if proof_id not in self.rows:
            raise KeyError("Design proof not found.")
        if not str(comment or "").strip():
            raise ValueError("Please describe the requested changes.")
        self.actions.append(("changes", proof_id, comment))
        return {"id": proof_id, "status": "changes_requested"}


class _Log:
    def error(self, title, exc):
        pass


class WsgiCustomerQuoteProofRouteTests(unittest.TestCase):
    def setUp(self):
        self.vault_dir = tempfile.TemporaryDirectory()
        self.outside_dir = tempfile.TemporaryDirectory()
        self.core = SimpleNamespace(
            security=_Security(),
            quotes=_Quotes(),
            design_proofs=_Proofs(),
            design_vault=SimpleNamespace(root=self.vault_dir.name),
            error_log=_Log(),
        )
        self.api = FabOSAPI(self.core)
        self.customer = {"Authorization": "Bearer customer-token"}
        self.employee = {"Authorization": "Bearer employee-token"}

    def tearDown(self):
        self.vault_dir.cleanup()
        self.outside_dir.cleanup()

    def test_proofs_list_requires_customer_account(self):
        self.assertEqual(self.api.request("GET", "/api/v1/customer/proofs")["status"], 401)
        denied = self.api.request("GET", "/api/v1/customer/proofs", headers=self.employee)
        self.assertEqual(denied["status"], 401)

    def test_proofs_list_returns_proofs(self):
        self.core.design_proofs.rows["p1"] = {"id": "p1", "status": "sent"}
        result = self.api.request("GET", "/api/v1/customer/proofs", headers=self.customer)
        self.assertEqual(result["status"], 200)
        self.assertEqual([p["id"] for p in result["data"]["proofs"]], ["p1"])

    def test_single_proof_get(self):
        self.core.design_proofs.rows["p1"] = {"id": "p1", "status": "sent"}
        result = self.api.request("GET", "/api/v1/customer/proofs/p1", headers=self.customer)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["proof"]["id"], "p1")
        missing = self.api.request("GET", "/api/v1/customer/proofs/nope", headers=self.customer)
        self.assertEqual(missing["status"], 404)

    def test_accept_quote_happy_path(self):
        self.core.quotes.statuses["q1"] = {"id": "q1", "status": "sent", "expires_at": "2099-01-01"}
        result = self.api.request("POST", "/api/v1/customer/quotes/q1/accept", {}, self.customer)
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["data"]["accepted"])
        self.assertEqual(result["data"]["order_id"], "order-q1")
        self.assertEqual(self.core.quotes.statuses["q1"]["status"], "accepted")

    def test_accept_quote_wrong_status_is_409(self):
        self.core.quotes.statuses["q2"] = {"id": "q2", "status": "draft", "expires_at": ""}
        result = self.api.request("POST", "/api/v1/customer/quotes/q2/accept", {}, self.customer)
        self.assertEqual(result["status"], 409)
        self.assertNotIn("q2", self.core.quotes.converted)

    def test_accept_expired_quote_is_409_and_marked_expired(self):
        self.core.quotes.statuses["q3"] = {"id": "q3", "status": "sent", "expires_at": "2001-01-01"}
        result = self.api.request("POST", "/api/v1/customer/quotes/q3/accept", {}, self.customer)
        self.assertEqual(result["status"], 409)
        self.assertEqual(self.core.quotes.statuses["q3"]["status"], "expired")

    def test_accept_already_approved_quote_is_idempotent(self):
        self.core.quotes.statuses["q4"] = {"id": "q4", "status": "approved", "expires_at": ""}
        result = self.api.request("POST", "/api/v1/customer/quotes/q4/accept", {}, self.customer)
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["data"]["accepted"])

    def test_accept_missing_quote_is_404(self):
        result = self.api.request("POST", "/api/v1/customer/quotes/nope/accept", {}, self.customer)
        self.assertEqual(result["status"], 404)

    def test_decline_quote(self):
        self.core.quotes.statuses["q5"] = {"id": "q5", "status": "sent", "expires_at": ""}
        result = self.api.request("POST", "/api/v1/customer/quotes/q5/decline", {}, self.customer)
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["data"]["declined"])
        self.assertEqual(self.core.quotes.statuses["q5"]["status"], "declined")

    def test_decline_non_sent_quote_is_409(self):
        self.core.quotes.statuses["q6"] = {"id": "q6", "status": "accepted", "expires_at": ""}
        result = self.api.request("POST", "/api/v1/customer/quotes/q6/decline", {}, self.customer)
        self.assertEqual(result["status"], 409)

    def test_approve_proof(self):
        self.core.design_proofs.rows["p1"] = {"id": "p1", "status": "sent"}
        result = self.api.request("POST", "/api/v1/customer/proofs/p1/approve", {"comment": "Looks good"}, self.customer)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["proof"]["status"], "approved")
        self.assertEqual(self.core.design_proofs.actions[0], ("approve", "p1", "Looks good"))

    def test_approve_reviewed_proof_is_409(self):
        self.core.design_proofs.rows["p2"] = {"id": "p2", "status": "approved"}
        result = self.api.request("POST", "/api/v1/customer/proofs/p2/approve", {}, self.customer)
        self.assertEqual(result["status"], 409)

    def test_request_changes_requires_comment(self):
        self.core.design_proofs.rows["p3"] = {"id": "p3", "status": "sent"}
        empty = self.api.request("POST", "/api/v1/customer/proofs/p3/request-changes", {"comment": " "}, self.customer)
        self.assertEqual(empty["status"], 400)
        ok = self.api.request("POST", "/api/v1/customer/proofs/p3/request-changes", {"comment": "Fix the corner"}, self.customer)
        self.assertEqual(ok["status"], 200)
        self.assertEqual(ok["data"]["proof"]["status"], "changes_requested")

    def test_proof_file_serves_bytes_with_content_type(self):
        payload = b"PNG-DATA"
        target = Path(self.vault_dir.name) / "proof.png"
        target.write_bytes(payload)
        self.core.design_proofs.rows["p4"] = {
            "id": "p4", "status": "sent", "stored_path": str(target), "original_name": "review.png",
        }
        result = self.api.request("GET", "/api/v1/customer/proofs/p4/file", headers=self.customer)
        self.assertEqual(result["status"], 200)
        info = result["data"]["_wsgi_file"]
        self.assertEqual(info["bytes"], payload)
        self.assertEqual(info["content_type"], "image/png")
        self.assertEqual(info["filename"], "review.png")

    def test_proof_file_outside_vault_is_404(self):
        outside = Path(self.outside_dir.name) / "evil.png"
        outside.write_bytes(b"evil")
        self.core.design_proofs.rows["p5"] = {
            "id": "p5", "status": "sent", "stored_path": str(outside), "original_name": "evil.png",
        }
        result = self.api.request("GET", "/api/v1/customer/proofs/p5/file", headers=self.customer)
        self.assertEqual(result["status"], 404)

    def test_proof_file_without_stored_path_is_404(self):
        self.core.design_proofs.rows["p6"] = {"id": "p6", "status": "sent", "stored_path": "", "original_name": ""}
        result = self.api.request("GET", "/api/v1/customer/proofs/p6/file", headers=self.customer)
        self.assertEqual(result["status"], 404)

    def test_wsgi_adapter_serves_proof_file_as_binary(self):
        payload = b"%PDF-1.4 fake"
        target = Path(self.vault_dir.name) / "proof.pdf"
        target.write_bytes(payload)
        self.core.design_proofs.rows["p7"] = {
            "id": "p7", "status": "sent", "stored_path": str(target), "original_name": "proof.pdf",
        }
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/customer/proofs/p7/file", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
            "HTTP_AUTHORIZATION": "Bearer customer-token", "HTTP_USER_AGENT": "test", "REMOTE_ADDR": "127.0.0.1",
        }
        captured = {}

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = dict(headers)

        body = b"".join(create_wsgi_app(self.core)(environ, start_response))
        self.assertEqual(captured["status"], "200 OK")
        self.assertEqual(body, payload)
        self.assertIn("application/pdf", captured["headers"]["Content-Type"])
        self.assertIn("attachment", captured["headers"]["Content-Disposition"])
        self.assertEqual(captured["headers"]["Content-Length"], str(len(payload)))


if __name__ == "__main__":
    unittest.main()
