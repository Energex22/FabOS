import sqlite3
import unittest
from contextlib import contextmanager

from fabos_core.services.accounts import AccountService


class InMemoryDatabase:
    def __init__(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """CREATE TABLE users(
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT,
                account_type TEXT NOT NULL,
                active INTEGER NOT NULL DEFAULT 1,
                role TEXT,
                created_at TEXT,
                updated_at TEXT
            )"""
        )

    @contextmanager
    def connect(self):
        yield self.connection


class AccountAdminSafetyTests(unittest.TestCase):
    def setUp(self):
        self.db = InMemoryDatabase()
        self.service = AccountService(self.db)
        self.db.connection.executemany(
            "INSERT INTO users(id,username,email,account_type,active,created_at,updated_at) VALUES(?,?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            [
                ("admin-1", "admin1", "admin1@example.com", "administrator"),
                ("employee-1", "employee1", "employee@example.com", "employee"),
            ],
        )
        self.db.connection.execute("UPDATE users SET role='owner' WHERE id='admin-1'")
        self.db.connection.commit()

    def test_owner_cannot_be_disabled_even_when_another_admin_exists(self):
        self.db.connection.execute("INSERT INTO users(id,username,email,account_type,active,created_at,updated_at,role) VALUES(?,?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?)", ("admin-2","admin2","admin2@example.com","administrator","administrator"))
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, "owner account"):
            self.service.update_account("admin-1", active=False)

    def test_owner_cannot_be_demoted_even_when_another_admin_exists(self):
        self.db.connection.execute("INSERT INTO users(id,username,email,account_type,active,created_at,updated_at,role) VALUES(?,?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,?)", ("admin-2","admin2","admin2@example.com","administrator","administrator"))
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, "owner account"):
            self.service.update_account("admin-1", account_type="employee")

    def test_owner_cannot_be_linked_as_customer(self):
        with self.assertRaisesRegex(ValueError, "owner account"):
            self.service.link_customer("admin-1", "missing-customer")

    def test_owner_cannot_be_changed_to_employee_profile(self):
        with self.assertRaisesRegex(ValueError, "owner account"):
            self.service.set_employee_profile("admin-1")

    def test_last_active_administrator_cannot_be_disabled(self):
        self.db.connection.execute("UPDATE users SET role='administrator' WHERE id='admin-1'")
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, "last active administrator"):
            self.service.update_account("admin-1", active=False)
        self.assertEqual(self.service.get_user("admin-1")["active"], 1)

    def test_last_active_administrator_cannot_be_demoted(self):
        self.db.connection.execute("UPDATE users SET role='administrator' WHERE id='admin-1'")
        self.db.connection.commit()
        with self.assertRaisesRegex(ValueError, "last active administrator"):
            self.service.update_account("admin-1", account_type="employee")
        self.assertEqual(self.service.get_user("admin-1")["account_type"], "administrator")

    def test_administrator_can_be_changed_when_another_active_administrator_exists(self):
        self.db.connection.execute(
            "INSERT INTO users(id,username,email,account_type,active,created_at,updated_at) VALUES(?,?,?,?,1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
            ("admin-2", "admin2", "admin2@example.com", "administrator"),
        )
        self.db.connection.commit()
        self.db.connection.execute("UPDATE users SET role='administrator' WHERE id='admin-1'")
        self.db.connection.commit()

        updated = self.service.update_account("admin-1", account_type="employee", active=True)

        self.assertEqual(updated["account_type"], "employee")
        self.assertEqual(updated["active"], 1)
        self.assertEqual(self.service.get_user("admin-2")["account_type"], "administrator")

    def test_non_administrator_account_can_still_be_disabled(self):
        updated = self.service.update_account("employee-1", active=False)
        self.assertEqual(updated["active"], 0)


if __name__ == "__main__":
    unittest.main()
