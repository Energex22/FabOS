from datetime import datetime
from pathlib import Path
import sqlite3

class BackupService:
    def __init__(self,source,destination):
        self.source=Path(source);self.destination=Path(destination)

    def create(self,label=""):
        self.destination.mkdir(parents=True,exist_ok=True)
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        safe="".join(ch for ch in str(label) if ch.isalnum() or ch in ("-","_"))[:30]
        suffix=("_"+safe) if safe else ""
        target=self.destination/("fabos_%s%s.sqlite3"%(stamp,suffix))
        s=sqlite3.connect(str(self.source));d=sqlite3.connect(str(target))
        try:s.backup(d)
        finally:d.close();s.close()
        return target

    def create_daily_if_needed(self):
        self.destination.mkdir(parents=True,exist_ok=True)
        today=datetime.now().strftime("%Y%m%d")
        if any(self.destination.glob("fabos_%s*.sqlite3"%today)):
            return None
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
        if not src.exists():raise FileNotFoundError(src)
        # Preserve current DB immediately before restore.
        safety=self.create("pre_restore")
        source=sqlite3.connect(str(src));dest=sqlite3.connect(str(self.source))
        try:
            check=source.execute("PRAGMA integrity_check").fetchone()[0]
            if str(check).lower()!="ok":
                raise ValueError("Selected backup failed SQLite integrity check: "+str(check))
            source.backup(dest)
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
        files=sorted(self.destination.glob("fabos_*.sqlite3"),
                     key=lambda p:p.stat().st_mtime,reverse=True)
        removed=[]
        for p in files[int(keep):]:
            p.unlink();removed.append(p)
        return removed
