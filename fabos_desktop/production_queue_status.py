from __future__ import absolute_import

def status_text(decision):
    if decision.get("eligible"):
        w=decision.get("warnings") or []
        return "READY — "+w[0] if w else "READY — proceed to normal printer preflight"
    r=decision.get("reasons") or ["Production job is blocked."]
    return "BLOCKED — "+r[0]

def status_lines(decision):
    return [status_text(decision)]+["• "+x for x in decision.get("reasons",[])]+["⚠ "+x for x in decision.get("warnings",[])]
