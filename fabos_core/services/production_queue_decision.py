from __future__ import absolute_import

class ProductionQueueDecision(object):
    """Deterministic READY/BLOCKED explanation; never starts hardware."""
    TERMINAL=set(("completed","cancelled","failed","archived"))

    def __init__(self, app):
        self.app=app

    def decide(self, job, printer_id=None):
        reasons=[]; warnings=[]
        status=str(job.get("status","")).lower()
        if status in self.TERMINAL: reasons.append("Job is already in a terminal state.")
        if status in ("printing","paused","running"): reasons.append("Job is already active on a printer.")
        try:
            if int(job.get("quantity",1)) < 1: reasons.append("Job quantity is less than 1.")
        except Exception: reasons.append("Job quantity is invalid.")
        assigned=job.get("printer_id"); selected=printer_id or assigned
        if not selected: reasons.append("No printer is assigned.")
        elif assigned and printer_id and str(assigned)!=str(printer_id):
            warnings.append("Selected printer differs from the job's assigned printer.")
        if not job.get("product_id"): reasons.append("Job has no product assigned.")
        if job.get("order_id"):
            try: order=self.app.orders.get(job.get("order_id"))
            except Exception: order=None
            if not order: warnings.append("Linked order could not be resolved; verify the order before launch.")
        return {"eligible":not reasons,"reasons":reasons,"warnings":warnings,
                "status":"ready" if not reasons else "blocked",
                "summary":"Ready for printer preflight." if not reasons else reasons[0]}
