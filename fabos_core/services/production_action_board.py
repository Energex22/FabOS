from __future__ import absolute_import

class ProductionActionBoard(object):
    """Read-only aggregation of production next-action decisions."""

    def __init__(self, app):
        self.app = app

    def build(self, jobs=None):
        if jobs is None:
            jobs = self.app.production.list_jobs()

        rows = []
        counts = {
            "total": 0,
            "blocked": 0,
            "monitor": 0,
            "assign_printer": 0,
            "preflight": 0,
        }

        for job in jobs or []:
            action = self.app.production_next_action.for_job(job)
            item = {
                "job_id": job.get("id"),
                "order_id": job.get("order_id"),
                "product_id": job.get("product_id"),
                "status": job.get("status"),
                "priority": job.get("priority"),
                "due_at": job.get("due_at"),
                "action": action.get("action"),
                "label": action.get("label"),
                "safe_to_start": bool(action.get("safe_to_start")),
                "reason": action.get("reason", ""),
                "blockers": list(action.get("blockers") or []),
                "warnings": list(action.get("warnings") or []),
            }
            rows.append(item)
            counts["total"] += 1
            if item["action"] in counts:
                counts[item["action"]] += 1

        return {"rows": rows, "counts": counts}
