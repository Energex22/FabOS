from pathlib import Path
from datetime import datetime,timedelta
import json,traceback,os

class ErrorLogService:
    def __init__(self,log_dir):
        self.log_dir=Path(log_dir);self.log_dir.mkdir(parents=True,exist_ok=True)
        self.path=self.log_dir/"fabos.log"

    def _write(self,level,message,detail="",context=None):
        stamp=datetime.now().isoformat(timespec="seconds")
        record={"time":stamp,"level":level,"message":str(message),"detail":str(detail or ""),
                "context":context or {}}
        with self.path.open("a",encoding="utf-8") as f:
            f.write(json.dumps(record,ensure_ascii=False)+"\n")
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
            try:out.append(json.loads(line))
            except Exception:pass
        return out

    def prune(self,days=30):
        if not self.path.exists():return
        # Keep the file bounded by retaining recent 10k records. Timestamps remain in every line.
        lines=self.path.read_text(encoding="utf-8",errors="ignore").splitlines()
        if len(lines)>10000:self.path.write_text("\n".join(lines[-10000:])+"\n",encoding="utf-8")
