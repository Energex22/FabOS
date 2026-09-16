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


class _Core:
    def __init__(self, structured=True):
        self.security = _Security(structured)
        self.accounts = _Accounts()


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


if __name__ == "__main__":
    unittest.main()
