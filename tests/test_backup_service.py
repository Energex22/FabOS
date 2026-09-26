import sqlite3
from pathlib import Path

from fabos_core.services.backup import BackupService


def _seed_db(path: Path):
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


def test_create_and_validate_backup(tmp_path):
    source = tmp_path / "fabos.sqlite3"
    backups = tmp_path / "Backups"
    _seed_db(source)

    service = BackupService(source, backups)
    target = service.create("test")

    result = service.validate_backup(target)
    assert target.exists()
    assert result["valid"] is True
    assert result["bytes"] > 0


def test_test_latest_reports_missing_backup(tmp_path):
    source = tmp_path / "fabos.sqlite3"
    _seed_db(source)

    service = BackupService(source, tmp_path / "Backups")
    result = service.test_latest()

    assert result == {"valid": False, "detail": "No backup exists yet"}


def test_test_latest_validates_newest_backup(tmp_path):
    source = tmp_path / "fabos.sqlite3"
    backups = tmp_path / "Backups"
    _seed_db(source)
    service = BackupService(source, backups)

    service.create("first")
    newest = service.create("second")
    result = service.test_latest()

    assert result["valid"] is True
    assert result["bytes"] == newest.stat().st_size
