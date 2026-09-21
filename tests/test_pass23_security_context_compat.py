import unittest

from fabos_api import FabOSAPI


class _Security:
    def __init__(self, structured=True):
        self.structured = structured

    def context(self, token, permission=None):
        if self.structured:
            return {
                "user": {"id": "customer-1", "account_type": "customer"},
                "session": {"user_id": "customer-1"},
            }
        return {"id": "customer-1"}


class _Accounts:
    def account_summary(self, user_id):
        return {"id": user_id, "account_type": "customer", "active": True}


class _Products:
    _ROWS = [
        {"id": "p1", "name": "Widget", "category": "Home", "price_cents": 2450},
        {"id": "p2", "name": "Riser", "category": "Desk", "price_cents": 1800},
    ]

    def list(self, *args, **kwargs):
        return list(self._ROWS)

    def customer_catalog(self, query="", category="All", order_by="name", descending=False):
        # The legacy WSGI surface reads the published/ready projection, not the
        # raw product list, and expects (row, readiness) pairs.
        return [(row, {"ready": True}) for row in self._ROWS]

    def images(self, _product_id):
        return []

    def categories(self):
        return ["Home", "Desk"]


class _Core:
    def __init__(self, structured=True):
        self.security = _Security(structured)
        self.accounts = _Accounts()
        self.products = _Products()


class Pass23SecurityContextCompatibilityTests(unittest.TestCase):
    def test_api_context_exposes_actor_fields_for_existing_routes(self):
        api = FabOSAPI(_Core())
        context = api._context({"Authorization": "Bearer token"})
        self.assertEqual(context["id"], "customer-1")
        self.assertEqual(context["account_type"], "customer")
        self.assertEqual(context["user"]["id"], "customer-1")

    def test_legacy_id_only_context_resolves_account_type(self):
        api = FabOSAPI(_Core(structured=False))
        context = api._context({"Authorization": "Bearer token"})
        self.assertEqual(context["id"], "customer-1")
        self.assertEqual(context["account_type"], "customer")

    def test_public_catalog_does_not_require_authentication(self):
        api = FabOSAPI(_Core())
        result = api.request("GET", "/api/v1/catalog")
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["products"][0]["price"], 24.5)

    def test_public_catalog_categories_does_not_require_authentication(self):
        api = FabOSAPI(_Core())
        result = api.request("GET", "/api/v1/catalog/categories")
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["categories"], ["Desk", "Home"])


if __name__ == "__main__": unittest.main()
