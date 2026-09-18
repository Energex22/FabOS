from pathlib import Path
from datetime import datetime
import json,traceback,re

_REDACTED = "***REDACTED***"
_SENSITIVE_TEXT = re.compile(
    r"(Bearer\s+)[A-Za-z0-9._~+/=-]+|"
    r"((?:password|token|secret|api[_ -]?key|authorization|cookie|credential)[\s=:]+)(?:Bearer\s+)?[^\s,;]+",
    re.IGNORECASE,
)

def _redact(value):
    if isinstance(value, dict):
        return {str(k): _REDACTED if any(part in str(k).lower().replace("-", "_") for part in ("password", "token", "secret", "api_key", "authorization", "cookie", "credential", "private_key")) else _redact(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    if isinstance(value, str):
        return _SENSITIVE_TEXT.sub(lambda m: (m.group(1) or m.group(2)) + _REDACTED, value)
    return value

class ErrorLogService:
    def __init__(self,log_dir):
        self.log_dir=Path(log_dir);self.log_dir.mkdir(parents=True,exist_ok=True)
        self.path=self.log_dir/"fabos.log"

    def _write(self,level,message,detail="",context=None):
        stamp=datetime.now().isoformat(timespec="seconds")
        record={"time":stamp,"level":level,"message":_redact(str(message)),"detail":_redact(str(detail or "")),
                "context":_redact(context or {})}
        with self.path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(record,ensure_ascii=False)+"
")
        return record

    def info(self,message,detail="",context=None):return self._write("INFO",message,detail,context)
    def warning(self,message,detail="",context=None):return self._write("WARNING",message,detail,context)
    def error(self,message,exc=None,context=None):
        detail=""
        if exc is not None:
            detail="".join(traceback.format_exception(type(exc),exc,exc.__traceback__))
        return self._write("ERROR",message,detail,context)

    def recent(self,limit=200):
        if not self.path.exists():return []
        lines=self.path.read_text(encoding="utf-8",errors="ignore").splitlines()[-int(limit):]
        out=[]
        for line in reversed(lines):
            try:out.append(_redact(json.loads(line)))
            except Exception:pass
        return out

    def prune(self,days=30):
        if not self.path.exists():return
        lines=self.path.read_text(encoding="utf-8",errors="ignore").splitlines()
        if len(lines)>10000:self.path.write_text("
".join(lines[-10000:])+"
",encoding="utf-8")
