from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
from pathlib import Path
from zipfile import BadZipFile, ZipFile


def _safe_member(name: str) -> bool:
    path = Path(name)
    return not path.is_absolute() and ".." not in path.parts


def verify_backup(archive_path: str | Path) -> tuple[bool, str]:
    archive_path = Path(archive_path).expanduser()
    if not archive_path.is_file():
        return False, f"Backup archive not found: {archive_path}"
    try:
        with ZipFile(archive_path, "r") as archive:
            members = archive.namelist()
            if "fabos.sqlite3" not in members:
                return False, "Backup archive does not contain fabos.sqlite3"
            unsafe = [name for name in members if not _safe_member(name)]
            if unsafe:
                return False, f"Backup contains unsafe archive path: {unsafe[0]}"
            with tempfile.TemporaryDirectory(prefix="fabos-backup-verify-") as temp:
                root = Path(temp)
                archive.extractall(root)
                db_path = root / "fabos.sqlite3"
                connection = sqlite3.connect(db_path)
                try:
                    result = connection.execute("PRAGMA integrity_check").fetchone()[0]
                    if result != "ok":
                        return False, f"SQLite integrity check failed: {result}"
                    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if not tables:
                        return False, "Backup database contains no tables"
                finally:
                    connection.close()
    except (BadZipFile, OSError, sqlite3.Error) as exc:
        return False, f"Backup verification failed: {exc}"
    return True, f"Backup verified: {archive_path}"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify a FabOS backup archive without modifying live data.")
    parser.add_argument("archive", help="Path to a fabos-backup-*.zip archive")
    args = parser.parse_args(argv)
    ok, message = verify_backup(args.archive)
    print(message, file=sys.stdout if ok else sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
