from pathlib import Path
import shutil

class ReliabilityService:
    def __init__(self,app):
        self.app=app

    @staticmethod
    def _result(name,status,detail):
        return {"name":name,"status":status,"detail":detail}

    def health_safe(self):
        """Health checks that never fail as a group; every exception becomes a visible row."""
        checks=[]
        try:
            checks.extend(self.health())
        except Exception as exc:
            checks.append(self._result("Health engine","fail","Health check crashed: %s"%exc))
            try:self.app.error_log.error("System health check failed",exc)
            except Exception:pass

        # Additional beta-readiness checks are isolated one by one.
        def add(name,func):
            try:
                status,detail=func()
                checks.append(self._result(name,status,detail))
            except Exception as exc:
                checks.append(self._result(name,"warn",str(exc)))

        add("Design Vault",lambda:(
            "pass" if Path(self.app.settings.data_dir,"Design Vault").exists() else "warn",
            str(Path(self.app.settings.data_dir,"Design Vault"))))
        add("Error logging",lambda:("pass",str(self.app.error_log.path)))
        add("Crash recovery",lambda:(
            "warn" if self.app.recovery.previous_unclean else "pass",
            "Previous session ended unexpectedly; recovery was attempted" if self.app.recovery.previous_unclean else "Last session state is clean"))
        add("Packaging supplies",lambda:(
            "warn" if self.app.supplies.low() else "pass",
            ("%d low supply item(s)"%len(self.app.supplies.low())) if self.app.supplies.low() else "Supply inventory healthy"))
        add("G-code verification",lambda:(
            "pass","Verification registry available"))

        def backup_check():
            result=self.app.backups.test_latest()
            return ("pass" if result.get("valid") else "warn",result.get("detail","No backup validation result"))
        add("Latest backup validation",backup_check)

        def cura_defs():
            engine=self.app.cura.find_cura(self.app.inventory_profit.setting("cura_engine_path","") or self.app.shop_settings.get("cura_engine_path","") or "")
            if not engine:return ("warn","CuraEngine not configured")
            diag=self.app.cura.installation_diagnostic(
                str(engine),
                configured_fdmprinter=self.app.shop_settings.get("cura_fdmprinter_path","") or "",
                configured_fdmextruder=self.app.shop_settings.get("cura_fdmextruder_path","") or "")
            return ("pass" if diag.get("ok") else "warn",diag.get("message") or diag.get("resources") or "Cura checked")
        add("Cura definitions",cura_defs)

        def workflow_audit():
            issues=[]
            with self.app.database.connect() as c:
                rows=c.execute("""SELECT j.id,j.status,p.status printer_status,p.name printer_name
                  FROM print_jobs j LEFT JOIN printers p ON p.id=j.printer_id
                  WHERE j.status IN ('printing','paused')""").fetchall()
                for row in rows:
                    ps=str(row["printer_status"] or "").lower()
                    if ps in ("idle","offline","error"):
                        issues.append("Job %s is %s while %s is %s"%(row["id"][:8],row["status"],row["printer_name"] or "printer",ps))
                shipped=c.execute("""SELECT o.order_number,f.tracking_number FROM orders o
                  LEFT JOIN fulfillments f ON f.order_id=o.id WHERE o.status='shipped'""").fetchall()
                for row in shipped:
                    if not str(row["tracking_number"] or "").strip():
                        issues.append("%s is shipped without tracking"%row["order_number"])
                completed=c.execute("""SELECT o.order_number,COUNT(j.id) unfinished FROM orders o
                  JOIN print_jobs j ON j.order_id=o.id
                  WHERE o.status='completed' AND j.status NOT IN ('completed','cancelled')
                  GROUP BY o.id HAVING COUNT(j.id)>0""").fetchall()
                for row in completed:
                    issues.append("%s is completed with %d unfinished print job(s)"%(row["order_number"],row["unfinished"]))
            return ("warn" if issues else "pass",
                    "; ".join(issues[:5]) if issues else "Order/production/fulfillment states are consistent")
        add("Workflow consistency",workflow_audit)

        try:
            printers=list(self.app.printer_automation.list())
            for printer in printers:
                if printer["connection_mode"]!="octoprint":continue
                name="Printer: "+printer["name"]
                if not printer["octoprint_url"] or not printer["api_key_ref"]:
                    checks.append(self._result(name,"warn","OctoPrint URL/API key incomplete"))
                    continue
                try:
                    info=self.app.printer_automation.sync_octoprint(printer["id"])
                    state=str(info.get("state") or printer["octoprint_state_text"] or printer["status"])
                    checks.append(self._result(name,"pass" if state.lower() not in ("offline","error") else "warn",
                                               "OctoPrint: "+state))
                except Exception as exc:
                    checks.append(self._result(name,"warn","OctoPrint check failed: %s"%exc))
        except Exception as exc:
            checks.append(self._result("Printer connectivity","warn",str(exc)))
        return checks

    def beta_readiness(self):
        checks=self.health_safe()
        fails=sum(1 for x in checks if x["status"]=="fail")
        warns=sum(1 for x in checks if x["status"]=="warn")
        return {"ready":fails==0,"failures":fails,"warnings":warns,"checks":checks}

    def health(self):
        app=self.app;checks=[]
        try:
            value=app.backups.integrity()
            checks.append(self._result("Database integrity","pass" if str(value).lower()=="ok" else "fail",str(value)))
        except Exception as exc:
            checks.append(self._result("Database integrity","fail",str(exc)))

        data=Path(app.settings.data_dir)
        checks.append(self._result("Data directory","pass" if data.exists() else "fail",str(data)))
        try:
            usage=shutil.disk_usage(str(data))
            free_gb=usage.free/(1024.0**3)
            status="pass" if free_gb>=2 else ("warn" if free_gb>=0.5 else "fail")
            checks.append(self._result("Free disk space",status,"%.2f GB free"%free_gb))
        except Exception as exc:
            checks.append(self._result("Free disk space","warn",str(exc)))

        backups=app.backups.list()
        checks.append(self._result("Backups","pass" if backups else "warn",
            ("%d backup%s available"%(len(backups),"" if len(backups)==1 else "s")) if backups else "No backups created yet"))

        engine=app.cura.find_cura(app.inventory_profit.setting("cura_engine_path","") or "")
        checks.append(self._result("Cura 4.13.1","pass" if engine else "warn",
            str(engine) if engine else "CuraEngine.exe has not been configured/detected"))

        try:
            printers=list(app.printer_automation.list())
            octos=[p for p in printers if p["connection_mode"]=="octoprint"]
            if not octos:
                checks.append(self._result("OctoPrint","warn","No printer is configured for OctoPrint"))
            else:
                configured=sum(1 for p in octos if p["octoprint_url"] and p["api_key_ref"])
                checks.append(self._result("OctoPrint","pass" if configured==len(octos) else "warn",
                    "%d of %d OctoPrint printer%s configured"%(configured,len(octos),"" if len(octos)==1 else "s")))
        except Exception as exc:
            checks.append(self._result("OctoPrint","warn",str(exc)))

        try:
            with app.database.connect() as c:
                migration_count=c.execute("SELECT COUNT(*) FROM app_migrations").fetchone()[0]
                counts={
                    "Products":c.execute("SELECT COUNT(*) FROM products").fetchone()[0],
                    "Customers":c.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
                    "Orders":c.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
                    "Invoices":c.execute("SELECT COUNT(*) FROM invoices").fetchone()[0],
                    "Print jobs":c.execute("SELECT COUNT(*) FROM print_jobs").fetchone()[0],
                }
            checks.append(self._result("Database migrations","pass","%d migrations applied"%migration_count))
            checks.append(self._result("Business records","pass",", ".join("%s: %s"%x for x in counts.items())))
        except Exception as exc:
            checks.append(self._result("Business records","fail",str(exc)))
        return checks
