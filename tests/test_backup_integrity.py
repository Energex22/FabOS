import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from deployment.windows.backup import main


class BackupIntegrityTests(unittest.TestCase):
    def test_backup_uses_sqlite_online_backup_and_includes_data_files(self):
        with tempfile.TemporaryDirectory() as temp:
            data_dir = Path(temp)
            db_path = data_dir / "fabos.sqlite3"
            (data_dir / "uploads").mkdir()
            (data_dir / "uploads" / "example.txt").write_text("backup me", encoding="utf-8")

            connection = sqlite3.connect(db_path)
            try:
                connection.execute("CREATE TABLE sample (value TEXT NOT NULL)")
                connection.execute("INSERT INTO sample(value) VALUES ('preserved')")
                connection.commit()
            finally:
                connection.close()

            old_data_dir = os.environ.get("FABOS_DATA_DIR")
            os.environ["FABOS_DATA_DIR"] = str(data_dir)
            try:
                self.assertEqual(main(), 0)
            finally:
                if old_data_dir is None:
                    os.environ.pop("FABOS_DATA_DIR", None)
                else:
                    os.environ["FABOS_DATA_DIR"] = old_data_dir

            backups = sorted((data_dir / "Backups").glob("fabos-backup-*.zip"))
            self.assertEqual(len(backups), 1)

            with tempfile.TemporaryDirectory() as restore:
                restore_dir = Path(restore)
                with ZipFile(backups[0]) as archive:
                    self.assertIn("fabos.sqlite3", archive.namelist())
                    self.assertIn("data/uploads/example.txt", archive.namelist())
                    archive.extractall(restore_dir)

                restored = sqlite3.connect(restore_dir / "fabos.sqlite3")
                try:
                    row = restored.execute("SELECT value FROM sample").fetchone()
                    self.assertEqual(row[0], "preserved")
                    integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
                    self.assertEqual(integrity, "ok")
                finally:
                    restored.close()

                self.assertEqual(
                    (restore_dir / "data" / "uploads" / "example.txt").read_text(encoding="utf-8"),
                    "backup me",
                )

    def test_backup_verifier_accepts_integrity_checked_archive(self):
        from deployment.windows.verify_backup import verify_backup
        import zipfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "fabos-backup-test.zip"
            db = root / "fabos.sqlite3"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO example(value) VALUES ('ok')")
            conn.commit()
            conn.close()
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(db, "fabos.sqlite3")
            ok, message = verify_backup(archive)
            self.assertTrue(ok, message)

    def test_backup_verifier_rejects_path_traversal(self):
        from deployment.windows.verify_backup import verify_backup
        import zipfile

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("fabos.sqlite3", b"not-a-database")
                zf.writestr("../outside.txt", b"unsafe")
            ok, message = verify_backup(archive)
            self.assertFalse(ok)
            self.assertIn("unsafe archive path", message)



if __name__ == "__main__":
    unittest.main()\n