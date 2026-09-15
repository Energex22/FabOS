import unittest

from fabos_api import FabOSAPI


class _Security:
    def context(self, token, permission=None):
        return {
            "user": {"id": "customer-1", "account_type": "customer"},
            "session": {"user_id": "customer-1"},
        }


class _Accounts:
    def account_summary(self, user_id):
        return {"id": user_id, "account_type": "customer", "active": True}


class _Core:
    security = _Security()
    accounts = _Accounts()


class Pass23SecurityContextCompatibilityTests(unittest.TestCase):
    def test_api_context_exposes_actor_fields_for_existing_routes(self):
        api = FabOSAPI(_Core())
        context = api._context({"Authorization": "Bearer token"})
        self.assertEqual(context["id"], "customer-1")
        self.assertEqual(context["account_type"], "customer")
        self.assertEqual(context["user"]["id"], "customer-1")


if __name__ == "__main__":
    unittest.main()
