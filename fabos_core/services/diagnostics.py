from pathlib import Path
from datetime import datetime
import json,platform,sys,zipfile

class DiagnosticsService:
    def __init__(self,app):self.app=app

    def version_info(self):
        try:
            from fabos_core import __version__
        except Exception:__version__="unknown"
        with self.app.database.connect() as c:
            schema=c.execute("SELECT COALESCE(MAX(version),0) FROM app_migrations").fetchone()[0]
        return {"fabos_version":__version__,"schema_version":int(schema or 0),
                "python":sys.version.split()[0],"platform":platform.platform(),
                "data_dir":str(self.app.settings.data_dir)}

    def export(self,target=None):
        out=Path(target) if target else Path(self.app.settings.data_dir)/("FabOS_Diagnostics_%s.zip"%datetime.now().strftime("%Y%m%d_%H%M%S"))
        health=[]
        try:health=self.app.reliability.health_safe()
        except Exception as exc:health=[{"name":"Health export","status":"fail","detail":str(exc)}]
        version=self.version_info()
        settings=self.app.shop_settings.snapshot()
        for key in list(settings):
            if "api" in key.lower() or "key" in key.lower() or "token" in key.lower() or "password" in key.lower():
                settings[key]="***REDACTED***"
        printers=[]
        try:
            for p in self.app.printer_automation.list():
                row=dict(p)
                if "api_key_ref" in row:row["api_key_ref"]="***REDACTED***"
                printers.append(row)
        except Exception:pass
        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("version.json",json.dumps(version,indent=2,default=str))
            z.writestr("health.json",json.dumps(health,indent=2,default=str))
            z.writestr("settings.json",json.dumps(settings,indent=2,default=str))
            z.writestr("printers.json",json.dumps(printers,indent=2,default=str))
            logs=Path(self.app.settings.log_dir)/"fabos.log"
            if logs.exists():z.write(logs,"logs/fabos.log")
            z.writestr("README.txt","FabOS diagnostics package. Secrets are redacted. Database contents are NOT included.")
        return out
