from pathlib import Path
from datetime import datetime
import json,os

class RecoveryService:
    def __init__(self,app):
        self.app=app
        self.marker=Path(app.settings.data_dir)/"runtime_session.json"
        self.previous_unclean=self.marker.exists()
        self.start_session()

    def start_session(self):
        self.marker.write_text(json.dumps({"pid":os.getpid(),"started_at":datetime.now().isoformat()}),encoding="utf-8")

    def clean_shutdown(self):
        try:self.marker.unlink()
        except FileNotFoundError:pass

    def reconcile(self):
        recovered=[]
        if not self.previous_unclean:return recovered
        for printer in self.app.printer_automation.list():
            if printer["connection_mode"]!="octoprint" or not printer["octoprint_url"] or not printer["api_key_ref"]:continue
            try:
                info=self.app.printer_automation.sync_octoprint(printer["id"])
                state=str(info.get("state") or "").lower()
                active=self.app.printer_automation.active_job(printer["id"])
                if state in ("printing","paused") and active:
                    with self.app.database.connect() as c:
                        c.execute("UPDATE print_jobs SET status=? WHERE id=?",
                                  ("paused" if state=="paused" else "printing",active["id"]))
                        c.commit()
                    recovered.append(active["id"])
            except Exception as exc:
                try:self.app.error_log.warning("Crash recovery printer sync failed",str(exc),{"printer":printer["name"]})
                except Exception:pass
        return recovered
