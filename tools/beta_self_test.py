import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from fabos_core.application import FabOSApplication

app=FabOSApplication()
results=app.beta_self_test.run()
print("\nWireVault FabOS Beta Self-Test\n"+"="*34)
failed=0
for row in results:
    mark="PASS" if row["status"]=="pass" else "FAIL"
    print("[%s] %-28s %s"%(mark,row["name"],row["detail"]))
    if row["status"]!="pass":failed+=1
try:app.recovery.clean_shutdown()
except Exception:pass
print("\nResult: %s"%("PASS" if failed==0 else "%d FAILED"%failed))
raise SystemExit(0 if failed==0 else 1)
