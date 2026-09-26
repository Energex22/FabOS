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

    def test_restore_rejects_invalid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fabos.sqlite3"
            backups = root / "Backups"
            self._seed_db(source)
            bad = backups / "bad.sqlite3"
            backups.mkdir()
            sqlite3.connect(bad).close()
            service = BackupService(source, backups)
            with self.assertRaises(ValueError):
                service.restore(bad)

    def test_create_removes_partial_backup_when_sqlite_backup_fails(self):
        service = BackupService(self.database_path, self.backup_dir)
        original = sqlite3.Connection.backup
        try:
            def fail_backup(*args, **kwargs):
                raise sqlite3.DatabaseError("simulated backup failure")
            sqlite3.Connection.backup = fail_backup
            with self.assertRaises(sqlite3.DatabaseError):
                service.create("failed")
        finally:
            sqlite3.Connection.backup = original
        self.assertEqual(list(self.backup_dir.glob("fabos_*.sqlite3")), [])

    def test_create_does_not_overwrite_same_second_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fabos.sqlite3"
            backups = root / "Backups"
            self._seed_db(source)
            service = BackupService(source, backups)
            first = service.create("same")
            second = service.create("same")
            self.assertNotEqual(first, second)
            self.assertTrue(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(len(service.list()), 2)

    def test_prune_rejects_invalid_retention(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fabos.sqlite3"
            self._seed_db(source)
            service = BackupService(source, root / "Backups")
            with self.assertRaises(ValueError):
                service.prune(keep=0)
            with self.assertRaises(ValueError):
                service.prune(keep="not-a-number")

    def test_prune_keeps_requested_number_of_backups(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "fabos.sqlite3"
            backups = root / "Backups"
            self._seed_db(source)
            service = BackupService(source, backups)
            for label in ("one", "two", "three"):
                service.create(label)
            removed = service.prune(keep=2)
            self.assertEqual(len(removed), 1)
            self.assertEqual(len(service.list()), 2)


if __name__ == "__main__":
    unittest.main()
