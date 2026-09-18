import tempfile
import unittest

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate


class MigrationRunnerTests(unittest.TestCase):
    def test_partial_duplicate_column_migration_continues_remaining_statements(self):
        with tempfile.TemporaryDirectory() as td:
            db = Database(td + "/fabos.db")
            db.initialize()
            with db.connect() as c:
                c.execute("CREATE TABLE IF NOT EXISTS app_migrations(version INTEGER PRIMARY KEY,name TEXT NOT NULL,applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                for version in range(1, 34):
                    c.execute("INSERT INTO app_migrations(version,name) VALUES(?,?)", (version, "migration_%03d" % version))
                c.execute("""CREATE TABLE fulfillments(
                    id TEXT PRIMARY KEY,
                    order_id TEXT NOT NULL,
                    method TEXT NOT NULL DEFAULT 'pickup',
                    status TEXT NOT NULL DEFAULT 'pending',
                    carrier TEXT,
                    tracking_number TEXT,
                    package_weight_oz REAL,
                    shipping_cost_cents INTEGER NOT NULL DEFAULT 0,
                    destination TEXT,
                    notes TEXT,
                    shipped_at TEXT,
                    delivered_at TEXT,
                    picked_up_at TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                c.execute("ALTER TABLE fulfillments ADD COLUMN package_length_in REAL")
                c.commit()
            migrate(db)
            with db.connect() as c:
                columns = {row["name"] for row in c.execute("PRAGMA table_info(fulfillments)")}
                self.assertIn("package_length_in", columns)
                self.assertIn("package_width_in", columns)
                self.assertIn("package_height_in", columns)
                self.assertEqual(c.execute("SELECT COUNT(*) FROM app_migrations WHERE version=34").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
