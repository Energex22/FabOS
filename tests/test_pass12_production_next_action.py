from __future__ import absolute_import

import unittest

from fabos_core.services.production_next_action import ProductionNextAction


class Decision(object):
    def __init__(self, eligible=True, reason="ok"):
        self.eligible = eligible
        self.reason = reason

    def as_dict(self):
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "blockers": [],
            "warnings": [],
        }


class QueueDecision(object):
    def __init__(self, eligible=True, reason="ok"):
        self.eligible = eligible
        self.reason = reason

    def decide(self, job):
        return {
            "eligible": self.eligible,
            "reason": self.reason,
            "blockers": [] if self.eligible else ["test blocker"],
            "warnings": [],
        }


class App(object):
    def __init__(self, eligible=True):
        self.production_queue_decision = QueueDecision(eligible)


class ProductionNextActionTests(unittest.TestCase):
    def test_blocked_job(self):
        result = ProductionNextAction(App(False)).for_job({"status": "queued"})
        self.assertEqual(result["action"], "blocked")
        self.assertFalse(result["safe_to_start"])

    def test_active_job_is_monitor(self):
        result = ProductionNextAction(App(True)).for_job({
            "status": "printing",
            "printer_id": 1,
        })
        self.assertEqual(result["action"], "monitor")
        self.assertFalse(result["safe_to_start"])

    def test_missing_printer_needs_assignment(self):
        result = ProductionNextAction(App(True)).for_job({"status": "queued"})
        self.assertEqual(result["action"], "assign_printer")
        self.assertFalse(result["safe_to_start"])

    def test_ready_job_points_to_preflight(self):
        result = ProductionNextAction(App(True)).for_job({
            "status": "queued",
            "printer_id": 1,
        })
        self.assertEqual(result["action"], "preflight")
        self.assertTrue(result["safe_to_start"])


if __name__ == "__main__":
    unittest.main()
