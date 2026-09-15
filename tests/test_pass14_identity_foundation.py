import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService


class Pass14IdentityFoundationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "fabos.db")
        self.db.initialize()
        migrate(self.db)
        self.accounts = AccountService(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_existing_user_gets_account_fields(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role) VALUES(?,?,?,?)",
                ("u1", "owner", "legacy-hash", "owner"),
            )
            conn.commit()
        # Migration 36 is applied during setUp, so emulate a legacy row inserted
        # after migration and verify the account service remains compatible.
        row = self.accounts.get_user("u1")
        self.assertEqual(row["username"], "owner")
        self.assertEqual(row["password_hash"], "legacy-hash")
        self.assertIn(row["account_type"], ("administrator", "employee", "customer"))

    def test_update_account_and_email_lookup(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,account_type) VALUES(?,?,?,?,?)",
                ("u2", "customer1", "hash", "customer", "customer"),
            )
            conn.commit()
        self.accounts.update_account("u2", email="Customer@Example.com")
        row = self.accounts.get_by_email("customer@example.com")
        self.assertEqual(row["id"], "u2")
        self.assertEqual(row["email"], "customer@example.com")

    def test_customer_link_is_one_to_one(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,account_type) VALUES(?,?,?,?,?)",
                ("u3", "customer1", "hash", "customer", "customer"),
            )
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,account_type) VALUES(?,?,?,?,?)",
                ("u4", "customer2", "hash", "customer", "customer"),
            )
            conn.execute("INSERT INTO customers(id,name) VALUES(?,?)", ("c1", "Customer One"))
            conn.commit()
        self.accounts.link_customer("u3", "c1")
        self.assertEqual(self.accounts.customer_for_user("u3")["id"], "c1")
        with self.assertRaises(ValueError):
            self.accounts.link_customer("u4", "c1")

    def test_employee_profile_is_separate_from_auth_user(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,account_type) VALUES(?,?,?,?,?)",
                ("u5", "worker", "hash", "employee", "employee"),
            )
            conn.commit()
        profile = self.accounts.set_employee_profile(
            "u5", department="Production", position="Print Technician"
        )
        self.assertEqual(profile["department"], "Production")
        self.assertEqual(profile["position"], "Print Technician")
        self.assertEqual(self.accounts.get_user("u5")["account_type"], "employee")

    def test_invalid_account_type_is_rejected(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,account_type) VALUES(?,?,?,?,?)",
                ("u6", "bad", "hash", "employee", "employee"),
            )
            conn.commit()
        with self.assertRaises(ValueError):
            self.accounts.update_account("u6", account_type="superuser")


if __name__ == "__main__":
    unittest.main()
