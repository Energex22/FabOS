from datetime import datetime
from pathlib import Path
import sqlite3,os

class BackupService:
    def __init__(self,source,destination):
        self.source=Path(source);self.destination=Path(destination)

    def create(self,label=""):
        if not self.source.is_file():
            raise FileNotFoundError("FabOS source database does not exist: %s" % self.source)
        self.destination.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        safe="".join(ch for ch in str(label) if ch.isalnum() or ch in ("-","_"))[:30]
        suffix=("_"+safe) if safe else ""
        target=self.destination/("fabos_%s%s.sqlite3"%(stamp,suffix))
        counter=1
        while target.exists():
            target=self.destination/("fabos_%s%s_%d.sqlite3"%(stamp,suffix,counter))
            counter += 1
        s = None
        d = None
        try:
            s = sqlite3.connect(str(self.source))
            d = sqlite3.connect(str(target))
            s.backup(d)
        except Exception:
            try:
                target.unlink()
            except OSError:
                pass
            raise
        finally:
            if d is not None:
                d.close()
            if s is not None:
                s.close()
        return target

    def create_daily_if_needed(self):
        self.destination.mkdir(parents=True,exist_ok=True)
        today=datetime.now().strftime("%Y%m%d")
        existing = sorted(self.destination.glob("fabos_%s*.sqlite3" % today), key=lambda p: p.stat().st_mtime, reverse=True)
        for candidate in existing:
            # A daily backup only needs to be a readable, internally consistent
            # SQLite database. Full schema validation remains the contract for
            # selecting a backup for restore or production preflight.
            try:
                with sqlite3.connect(str(candidate)) as conn:
                    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
                if str(integrity).lower() == "ok":
                    return None
            except Exception:
                pass
            try:
                candidate.unlink()
            except OSError:
                pass
        return self.create("startup")

    def list(self):
        self.destination.mkdir(parents=True,exist_ok=True)
        out=[]
        for p in sorted(self.destination.glob("fabos_*.sqlite3"),key=lambda x:x.stat().st_mtime,reverse=True):
            stat=p.stat()
            out.append({"path":p,"name":p.name,"bytes":stat.st_size,
                        "modified":datetime.fromtimestamp(stat.st_mtime)})
        return out

    def restore(self,backup_path):
        src=Path(backup_path)
        if not src.exists():
            raise FileNotFoundError(src)
        if src.resolve() == self.source.resolve():
            raise ValueError("Cannot restore the live database from itself")
        validation=self.validate_backup(src)
        if not validation.get("valid"):
            raise ValueError("Selected backup is not a valid FabOS database: "+str(validation.get("detail") or "unknown error"))
        # Preserve current DB immediately before restore.
        safety=self.create("pre_restore")
        source=sqlite3.connect(str(src));dest=sqlite3.connect(str(self.source))
        try:
            source.backup(dest)
            dest.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            dest.close();source.close()
        return safety

    def integrity(self,path=None):
        target=Path(path) if path else self.source
        con=sqlite3.connect(str(target))
        try:return con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:con.close()

    def validate_backup(self,path):
        path=Path(path)
        if not path.exists():return {"valid":False,"detail":"Backup file does not exist"}
        try:
            con=sqlite3.connect(str(path))
            integrity=con.execute("PRAGMA integrity_check").fetchone()[0]
            tables={r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            con.close()
            required={"products","orders","print_jobs","app_migrations"}
            missing=sorted(required-tables)
            valid=str(integrity).lower()=="ok" and not missing
            detail="Integrity OK" if valid else ("Missing tables: "+", ".join(missing) if missing else str(integrity))
            return {"valid":valid,"detail":detail,"bytes":path.stat().st_size}
        except Exception as exc:
            return {"valid":False,"detail":str(exc)}

    def test_latest(self):
        rows=self.list()
        if not rows:return {"valid":False,"detail":"No backup exists yet"}
        return self.validate_backup(rows[0]["path"])

    def prune(self,keep=30):
        try:
            keep=int(keep)
        except (TypeError,ValueError) as exc:
            raise ValueError("Backup retention must be an integer") from exc
        if keep < 1:
            raise ValueError("Backup retention must be at least 1")
        files=sorted(self.destination.glob("fabos_*.sqlite3"),
                     key=lambda p:p.stat().st_mtime,reverse=True)
        removed=[]
        for p in files[int(keep):]:
            p.unlink();removed.append(p)
        return removed
