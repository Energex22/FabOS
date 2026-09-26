import sqlite3
import tempfile
import unittest
from pathlib import Path

from fabos_core.services.backup import BackupService


class BackupServiceTests(unittest.TestCase):
    def _seed_db(self, path: Path):
        conn = sqlite3.connect(path)
        conn.executescript("""
            CREATE TABLE products(id TEXT PRIMARY KEY);
            CREATE TABLE orders(id TEXT PRIMARY KEY);
            CREATE TABLE print_jobs(id TEXT PRIMARY KEY);
            CREATE TABLE app_migrations(version INTEGER PRIMARY KEY);
            INSERT INTO products(id) VALUES ('p1');
        """)
        conn.commit()
        conn.close()

    def test_create_and_validate_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fabos.sqlite3"
            backups = root / "Backups"
            self._seed_db(source)

            service = BackupService(source, backups)
            target = service.create("test")

            result = service.validate_backup(target)
            self.assertTrue(target.exists())
            self.assertTrue(result["valid"])
            self.assertGreater(result["bytes"], 0)

    def test_test_latest_reports_missing_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fabos.sqlite3"
            self._seed_db(source)

            service = BackupService(source, root / "Backups")
            result = service.test_latest()

            self.assertEqual(result, {"valid": False, "detail": "No backup exists yet"})

    def test_test_latest_validates_newest_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fabos.sqlite3"
            backups = root / "Backups"
            self._seed_db(source)
            service = BackupService(source, backups)

            service.create("first")
            newest = service.create("second")
            result = service.test_latest()

            self.assertTrue(result["valid"])
            self.assertEqual(result["bytes"], newest.stat().st_size)


if __name__ == "__main__":
    unittest.main()
