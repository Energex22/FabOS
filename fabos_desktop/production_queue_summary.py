from __future__ import absolute_import

def build_queue_summary(planner):
    data = planner.summarize()
    return {
        "title": "Production Queue",
        "active": data["active"],
        "queued": data["queued"],
        "running": data["running"],
        "blocked": data["blocked"],
        "next_job": data["next"],
    }

def next_job_label(planner):
    job = planner.next_jobs(1)
    if not job:
        return "No queued production jobs"
    item = job[0]
    product = item.get("product_name") or item.get("product_id") or "Unnamed product"
    return "Next: %s" % product
