from __future__ import absolute_import

class ProductionNextAction(object):
    """Deterministic next-action guidance for a production job.

    This layer is advisory only. It never starts hardware or changes job state.
    """

    def __init__(self, app):
        self.app = app

    def for_job(self, job):
        decision = self.app.production_queue_decision.decide(job)

        if not decision.get("eligible"):
            return {
                "action": "blocked",
                "label": "Fix production issue",
                "safe_to_start": False,
                "reason": decision.get("reason", "Production job is blocked."),
                "blockers": decision.get("blockers", []),
                "warnings": decision.get("warnings", []),
            }

        status = str(job.get("status", "")).lower()
        if status in ("printing", "paused", "running"):
            return {
                "action": "monitor",
                "label": "Monitor active print",
                "safe_to_start": False,
                "reason": "This job is already active.",
                "blockers": [],
                "warnings": decision.get("warnings", []),
            }

        if not job.get("printer_id"):
            return {
                "action": "assign_printer",
                "label": "Assign printer",
                "safe_to_start": False,
                "reason": "A printer must be assigned before preflight.",
                "blockers": [],
                "warnings": decision.get("warnings", []),
            }

        return {
            "action": "preflight",
            "label": "Run printer preflight",
            "safe_to_start": True,
            "reason": "The job is eligible for the next safe production step.",
            "blockers": [],
            "warnings": decision.get("warnings", []),
        }
