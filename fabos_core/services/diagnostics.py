from pathlib import Path
from datetime import datetime
import json,platform,sys,zipfile,os,re

_REDACTED = "***REDACTED***"
_SENSITIVE_KEYS = {
    "password", "password_hash", "token", "access_token", "refresh_token",
    "secret", "secret_key", "api_key", "api_key_ref", "webhook_secret",
    "webhook_signature_key", "authorization", "cookie", "session", "session_id",
    "credential", "credentials", "private_key",
}
_SENSITIVE_TEXT = re.compile(
    r"(Bearer\s+)[A-Za-z0-9._~+/=-]+|"
    r"((?:authorization)[\s=:]+(?:Bearer\s+)?)[^\s,;]+|"
    r"((?:password|token|secret|api[_ -]?key|cookie|credential)[\s=:]+)[^\s,;]+",
    re.IGNORECASE,
)

def _sensitive_key(key):
    normalized = str(key or "").strip().lower().replace("-", "_").replace(" ", "_")
    return normalized in _SENSITIVE_KEYS or any(
        part in normalized for part in ("password", "token", "secret", "api_key", "credential", "private_key", "authorization")
    )

def redact(value):
    """Return a diagnostic-safe copy without credentials, tokens, or secrets."""
    if isinstance(value, dict):
        return {key: _REDACTED if _sensitive_key(key) else redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return _SENSITIVE_TEXT.sub(lambda m: (m.group(1) or m.group(2) or m.group(3)) + _REDACTED, value)
    return value

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

    def _safe_log_export(self, path):
        """Write a redacted copy of the application log; never ship the raw log."""
        if not path.exists():
            return None
        lines=[]
        for line in path.read_text(encoding="utf-8",errors="ignore").splitlines():
            try:
                lines.append(json.dumps(redact(json.loads(line)),ensure_ascii=False))
            except Exception:
                lines.append(redact(line))
        return "\n".join(lines)+"\n" if lines else ""

    def export(self,target=None):
        out=Path(target) if target else Path(self.app.settings.data_dir)/("FabOS_Diagnostics_%s.zip"%datetime.now().strftime("%Y%m%d_%H%M%S"))
        health=[]
        try:health=self.app.reliability.health_safe()
        except Exception as exc:health=[{"name":"Health export","status":"fail","detail":str(exc)}]
        version=self.version_info()
        settings=redact(self.app.shop_settings.snapshot())
        printers=[]
        try:
            for p in self.app.printer_automation.list():
                printers.append(redact(dict(p)))
        except Exception:pass
        with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
            z.writestr("version.json",json.dumps(redact(version),indent=2,default=str))
            z.writestr("health.json",json.dumps(redact(health),indent=2,default=str))
            z.writestr("settings.json",json.dumps(settings,indent=2,default=str))
            z.writestr("printers.json",json.dumps(printers,indent=2,default=str))
            logs=Path(self.app.settings.log_dir)/"fabos.log"
            safe_logs=self._safe_log_export(logs)
            if safe_logs:
                z.writestr("logs/fabos.log",safe_logs)
            z.writestr("README.txt","FabOS diagnostics package. Secrets, credentials, tokens, and authorization values are redacted. Database contents are NOT included.")
        return out
