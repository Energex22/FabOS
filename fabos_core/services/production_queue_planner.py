from __future__ import absolute_import

class ProductionQueuePlanner(object):
    """Pure queue-planning helpers for FabOS production.

    The planner does not start printers or perform network I/O. It only
    determines which jobs should be visible/eligible next.
    """

    TERMINAL = set(("completed", "cancelled", "failed", "archived"))

    def __init__(self, production_service):
        self.production = production_service

    def active_jobs(self):
        jobs = self.production.list_jobs()
        result = []
        for job in jobs:
            status = str(job.get("status", "")).lower()
            if status not in self.TERMINAL:
                result.append(job)
        return result

    def next_jobs(self, limit=10):
        jobs = self.active_jobs()

        def key(job):
            # Explicit priority wins; earlier due dates follow; FIFO is last.
            try:
                priority = int(job.get("priority", 0) or 0)
            except Exception:
                priority = 0
            due = str(job.get("due_date", "") or "")
            created = str(job.get("created_at", "") or "")
            return (-priority, due or "9999-99-99", created)

        jobs.sort(key=key)
        return jobs[:max(0, int(limit))]

    def has_active_duplicate(self, product_id, order_id=None):
        for job in self.active_jobs():
            if str(job.get("product_id")) != str(product_id):
                continue
            if order_id is None or str(job.get("order_id")) == str(order_id):
                return job
        return None

    def summarize(self):
        jobs = self.active_jobs()
        queued = 0
        running = 0
        blocked = 0
        for job in jobs:
            status = str(job.get("status", "")).lower()
            if status in ("printing", "paused", "running"):
                running += 1
            elif status in ("blocked", "attention", "needs_attention"):
                blocked += 1
            else:
                queued += 1
        return {
            "active": len(jobs),
            "queued": queued,
            "running": running,
            "blocked": blocked,
            "next": self.next_jobs(1)[0] if jobs else None,
        }
