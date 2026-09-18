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
