import tempfile
import unittest
from pathlib import Path

from fabos_api import FabOSAPI
from fabos_core.application import FabOSApplication


class Pass24CustomerAPITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.core = FabOSApplication(data_dir=Path(self.temp.name))
        self.core.database.initialize()
        self.core.database.migrate()
        self.api = FabOSAPI(self.core)

    def tearDown(self):
        self.temp.cleanup()

    def test_register_and_read_customer_profile(self):
        result = self.api.request(
            "POST",
            "/api/v1/auth/register",
            {"name": "Test Customer", "email": "api@example.com", "password": "password123"},
        )
        self.assertEqual(result["status"], 201)
        token = result["data"]["token"]
        profile = self.api.request(
            "GET",
            "/api/v1/customer/me",
            headers={"Authorization": "Bearer " + token},
        )
        self.assertEqual(profile["status"], 200)
        self.assertEqual(profile["data"]["customer"]["email"], "api@example.com")
        self.assertEqual(profile["data"]["user"]["account_type"], "customer")

    def test_non_customer_cannot_use_customer_profile_route(self):
        self.assertEqual(
            self.api.request("GET", "/api/v1/customer/me", headers={"Authorization": "Bearer invalid"})["status"],
            401,
        )


if __name__ == "__main__":
    unittest.main()
