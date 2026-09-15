import unittest

from fabos_api import FabOSAPI


class Security:
    def context(self, token, permission=None):
        if token != "customer-token":
            raise PermissionError("Invalid or expired session")
        return {"id": "u1"}


class Accounts:
    def account_summary(self, user_id):
        return {"id": user_id, "account_type": "customer", "active": True}


class Products:
    def list(self, *args): return [{"id": "p1", "name": "Widget"}]
    def get(self, product_id): return {"id": product_id, "name": "Widget"}
    def images(self, product_id): return [{"id": "img1"}]
    def variants(self, product_id): return [{"id": "v1"}]


class Customers:
    def list_for_user(self, *args): return [{"id": "c1"}]
    def get_for_user(self, user_id, customer_id):
        if customer_id != "c1": raise PermissionError("Customer access denied")
        return {"id": customer_id}


class Quotes:
    def list_for_user(self, *args): return [{"id": "q1", "customer_id": "c1"}]
    def get_for_user(self, user_id, quote_id): return ({"id": quote_id, "customer_id": "c1"}, [])


class Auth:
    def login(self, *args, **kwargs): return {"token": "customer-token"}
    def logout(self, token): return True


class Core:
    security = Security()
    accounts = Accounts()
    products = Products()
    customers = Customers()
    quotes = Quotes()
    auth = Auth()


class Pass22APIReadBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.api = FabOSAPI(Core())
        self.headers = {"Authorization": "Bearer customer-token"}

    def test_product_read_routes(self):
        self.assertEqual(self.api.request("GET", "/api/v1/products", headers=self.headers)["status"], 200)
        result = self.api.request("GET", "/api/v1/products/p1", headers=self.headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["images"][0]["id"], "img1")

    def test_customer_read_is_scoped(self):
        result = self.api.request("GET", "/api/v1/customers", headers=self.headers)
        self.assertEqual(len(result["data"]["customers"]), 1)
        self.assertEqual(self.api.request("GET", "/api/v1/customers/c1", headers=self.headers)["status"], 200)
        self.assertEqual(self.api.request("GET", "/api/v1/customers/c2", headers=self.headers)["status"], 403)

    def test_quote_read_is_scoped(self):
        result = self.api.request("GET", "/api/v1/quotes", headers=self.headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["quotes"][0]["customer_id"], "c1")
        self.assertEqual(self.api.request("GET", "/api/v1/quotes/q1", headers=self.headers)["status"], 200)

    def test_protected_read_requires_authentication(self):
        for path in ("/api/v1/products", "/api/v1/customers", "/api/v1/quotes"):
            self.assertEqual(self.api.request("GET", path)["status"], 401)


if __name__ == "__main__": unittest.main()
