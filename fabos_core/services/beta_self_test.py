from pathlib import Path
import tempfile,uuid

class BetaSelfTestService:
    def __init__(self,app):self.app=app

    def run(self):
        results=[]
        def check(name,fn):
            try:
                detail=fn()
                results.append({"name":name,"status":"pass","detail":str(detail or "OK")})
            except Exception as exc:
                results.append({"name":name,"status":"fail","detail":str(exc)})

        check("Database integrity",lambda:self.app.backups.integrity())
        check("Schema version",self._schema)
        check("Database write/rollback",self._transaction)
        check("Backup create + validate",self._backup)
        check("Design Vault",lambda:str(Path(self.app.settings.data_dir)/"Design Vault"))
        check("G-code safety engine",self._gcode)
        check("Global search",lambda:"Search service available" if self.app.global_search else "Missing")
        check("Diagnostics export",lambda:"Diagnostics service available" if self.app.diagnostics else "Missing")
        check("Recovery engine",lambda:"Recovery service available" if self.app.recovery else "Missing")
        check("Application health",self._health)
        return results

    def _schema(self):
        with self.app.database.connect() as c:
            ver=int(c.execute("SELECT COALESCE(MAX(version),0) FROM app_migrations").fetchone()[0] or 0)
        if ver<35:raise RuntimeError("Database schema is %d; expected at least 35"%ver)
        return "Schema %d"%ver

    def _transaction(self):
        test_id="selftest_"+str(uuid.uuid4())
        with self.app.database.connect() as c:
            c.execute("SAVEPOINT fabos_selftest")
            c.execute("""INSERT INTO activity_journal(id,event_type,title,detail)
                         VALUES(?,?,?,?)""",(test_id,"selftest","Self-test","Rolled back"))
            count=c.execute("SELECT COUNT(*) FROM activity_journal WHERE id=?",(test_id,)).fetchone()[0]
            c.execute("ROLLBACK TO fabos_selftest");c.execute("RELEASE fabos_selftest")
        if count!=1:raise RuntimeError("Database write did not round-trip")
        return "SQLite write/rollback OK"

    def _backup(self):
        path=self.app.backups.create("selftest")
        result=self.app.backups.validate_backup(path)
        if not result.get("valid"):raise RuntimeError(result.get("detail","Backup validation failed"))
        try:path.unlink()
        except Exception:pass
        return "Temporary backup validated"

    def _gcode(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/"selftest.gcode"
            p.write_text("M140 S60\nM104 S200\nG28\nG90\nG1 X10 Y10 E1\nG1 X20 Y20 E2\n",encoding="utf-8")
            result=self.app.cura.validate_print_gcode(p)
            if not result.get("valid"):raise RuntimeError("; ".join(result.get("problems",[])))
        return "Safety parser accepted known-good G-code"

    def _health(self):
        checks=self.app.reliability.health_safe()
        if not checks:raise RuntimeError("No health checks returned")
        fails=[x for x in checks if x["status"]=="fail"]
        if fails:raise RuntimeError("%d health failure(s)"%len(fails))
        return "%d checks returned"%len(checks)
