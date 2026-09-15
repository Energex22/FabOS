import json
import unittest

from fabos_api import FabOSAPI, create_wsgi_app


class _Security:
    def context(self, token, permission=None):
        if token != "good-token":
            raise PermissionError("Invalid or expired session")
        return {"id": "u1"}


class _Auth:
    def login(self, identifier, password, ip_address=None, user_agent=None):
        if identifier != "customer@example.com" or password != "correct-password":
            raise PermissionError("Invalid credentials")
        return {"token": "good-token", "expires_at": "2099-01-01T00:00:00", "user": {"id": "u1"}}

    def logout(self, token):
        return token == "good-token"


class _Accounts:
    def account_summary(self, user_id):
        return {"id": user_id, "account_type": "customer", "active": True}


class _Orders:
    def list_for_user(self, *args):
        return [{"id": "o1", "customer_id": "c1", "status": "pending"}]

    def get_for_user(self, user_id, order_id):
        return ({"id": order_id, "customer_id": "c1", "status": "pending"}, [])

    def set_status(self, order_id, status, actor_user_id=None):
        return {"id": order_id, "status": status, "actor_user_id": actor_user_id}


class _Invoices:
    def list_for_user(self, *args):
        return [{"id": "i1", "order_id": "o1", "total_cents": 1000}]

    def get_for_user(self, user_id, invoice_id):
        return ({"id": invoice_id, "order_id": "o1"}, [], [])


class _Fulfillment:
    def list_for_user(self, user_id):
        return [{"id": "f1", "order_id": "o1", "status": "pending"}]

    def get_for_user(self, user_id, fulfillment_id):
        return {"id": fulfillment_id, "order_id": "o1", "status": "pending"}


class _Log:
    def error(self, title, exc):
        pass


class _Core:
    security = _Security()
    auth = _Auth()
    accounts = _Accounts()
    orders = _Orders()
    invoices = _Invoices()
    fulfillment = _Fulfillment()
    error_log = _Log()


class Pass21APIBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.api = FabOSAPI(_Core())

    def test_health_is_public(self):
        result = self.api.request("GET", "/api/v1/health")
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["data"]["ok"])

    def test_login_and_bearer_me(self):
        login = self.api.request("POST", "/api/v1/auth/login", {
            "identifier": "customer@example.com", "password": "correct-password"
        })
        self.assertEqual(login["status"], 200)
        me = self.api.request("GET", "/api/v1/me", headers={"Authorization": "Bearer good-token"})
        self.assertEqual(me["status"], 200)
        self.assertEqual(me["data"]["user"]["id"], "u1")

    def test_unauthenticated_protected_route_is_rejected(self):
        result = self.api.request("GET", "/api/v1/orders")
        self.assertEqual(result["status"], 401)

    def test_customer_order_boundary_uses_existing_service(self):
        result = self.api.request("GET", "/api/v1/orders", headers={"Authorization": "Bearer good-token"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["orders"][0]["id"], "o1")

    def test_order_mutation_requires_existing_actor_boundary(self):
        result = self.api.request("PATCH", "/api/v1/orders/o1", {"status": "confirmed"},
                                  headers={"Authorization": "Bearer good-token"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["order"]["status"], "confirmed")
        self.assertEqual(result["data"]["order"]["actor_user_id"], "u1")

    def test_invoice_and_fulfillment_routes_are_actor_aware(self):
        headers = {"Authorization": "Bearer good-token"}
        invoices = self.api.request("GET", "/api/v1/invoices", headers=headers)
        fulfillment = self.api.request("GET", "/api/v1/fulfillments", headers=headers)
        self.assertEqual(invoices["status"], 200)
        self.assertEqual(fulfillment["status"], 200)
        self.assertEqual(invoices["data"]["invoices"][0]["id"], "i1")
        self.assertEqual(fulfillment["data"]["fulfillments"][0]["id"], "f1")

    def test_wsgi_adapter_returns_json(self):
        import io
        captured = {}
        environ = {
            "REQUEST_METHOD": "GET", "PATH_INFO": "/api/v1/health", "QUERY_STRING": "",
            "CONTENT_LENGTH": "0", "wsgi.input": io.BytesIO(b""),
            "HTTP_AUTHORIZATION": "", "HTTP_USER_AGENT": "test", "REMOTE_ADDR": "127.0.0.1",
        }

        def start_response(status, headers):
            captured["status"] = status
            captured["headers"] = headers

        payload = b"".join(create_wsgi_app(_Core())(environ, start_response))
        self.assertEqual(captured["status"], "200 OK")
        self.assertTrue(json.loads(payload)["ok"])


if __name__ == "__main__":
    unittest.main()
