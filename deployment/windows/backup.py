from __future__ import annotations

import os
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def main() -> int:
    data_dir = Path(os.environ.get("FABOS_DATA_DIR", Path.home() / "WireVault FabOS Data")).expanduser()
    db_path = data_dir / "fabos.sqlite3"
    backup_dir = data_dir / "Backups"
    if not db_path.exists():
        print(f"FabOS database not found: {db_path}", file=sys.stderr)
        return 2

    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"fabos-backup-{stamp}.zip"
    with tempfile.TemporaryDirectory(prefix="fabos-backup-") as temp:
        temp_dir = Path(temp)
        db_copy = temp_dir / "fabos.sqlite3"
        source = sqlite3.connect(db_path)
        destination = sqlite3.connect(db_copy)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()

        archive_root = temp_dir / "data"
        archive_root.mkdir()
        for item in data_dir.iterdir():
            if item.name in {"Backups", "fabos.sqlite3", "fabos.sqlite3-shm", "fabos.sqlite3-wal"}:
                continue
            destination_item = archive_root / item.name
            if item.is_dir():
                shutil.copytree(item, destination_item)
            else:
                shutil.copy2(item, destination_item)
        with ZipFile(target, "w", compression=ZIP_DEFLATED) as archive:
            archive.write(db_copy, "fabos.sqlite3")
            for path in archive_root.rglob("*"):
                if path.is_file():
                    archive.write(path, Path("data") / path.relative_to(archive_root))

    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
