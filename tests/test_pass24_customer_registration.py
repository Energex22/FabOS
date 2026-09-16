import unittest

from fabos_core.database import Database
from fabos_core.services.accounts import AccountService
from fabos_core.services.auth import AuthService
from fabos_core.services.customer_accounts import CustomerAccountService


class Pass24CustomerRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        self.db.initialize()
        self.db.migrate()
        self.accounts = AccountService(self.db)
        self.auth = AuthService(self.db, self.accounts)
        self.service = CustomerAccountService(self.db, self.accounts, self.auth)

    def test_register_creates_customer_account_and_session(self):
        result = self.service.register("Test Customer", "test@example.com", "password123")
        self.assertTrue(result["token"])
        user = self.accounts.get_by_email("test@example.com")
        self.assertEqual(user["account_type"], "customer")
        customer = self.accounts.customer_for_user(user["id"])
        self.assertEqual(customer["name"], "Test Customer")
        self.assertEqual(self.auth.authenticate(result["token"])["id"], user["id"])

    def test_duplicate_email_is_rejected(self):
        self.service.register("First", "test@example.com", "password123")
        with self.assertRaises(ValueError):
            self.service.register("Second", "TEST@example.com", "password123")

    def test_short_password_is_rejected(self):
        with self.assertRaises(ValueError):
            self.service.register("Test", "test@example.com", "short")


if __name__ == "__main__":
    unittest.main()
