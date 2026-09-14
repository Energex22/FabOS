import unittest

from fabos_core.services.production_queue_planner import ProductionQueuePlanner


class FakeProduction(object):
    def __init__(self, jobs):
        self.jobs = jobs

    def list_jobs(self):
        return list(self.jobs)


class ProductionQueuePlannerTests(unittest.TestCase):
    def test_terminal_jobs_are_excluded(self):
        p = ProductionQueuePlanner(FakeProduction([
            {"id": 1, "status": "queued"},
            {"id": 2, "status": "completed"},
            {"id": 3, "status": "failed"},
        ]))
        self.assertEqual([x["id"] for x in p.active_jobs()], [1])

    def test_priority_orders_first(self):
        p = ProductionQueuePlanner(FakeProduction([
            {"id": 1, "status": "queued", "priority": 0, "due_date": "2026-12-01"},
            {"id": 2, "status": "queued", "priority": 5, "due_date": "2026-12-20"},
        ]))
        self.assertEqual(p.next_jobs(1)[0]["id"], 2)

    def test_duplicate_detection(self):
        p = ProductionQueuePlanner(FakeProduction([
            {"id": 7, "product_id": "P1", "order_id": "O1", "status": "queued"},
            {"id": 8, "product_id": "P1", "order_id": "O2", "status": "queued"},
        ]))
        self.assertEqual(p.has_active_duplicate("P1", "O1")["id"], 7)
        self.assertEqual(p.has_active_duplicate("P1", "O9"), None)

    def test_summary(self):
        p = ProductionQueuePlanner(FakeProduction([
            {"id": 1, "status": "queued"},
            {"id": 2, "status": "printing"},
            {"id": 3, "status": "blocked"},
        ]))
        s = p.summarize()
        self.assertEqual(s["active"], 3)
        self.assertEqual(s["queued"], 1)
        self.assertEqual(s["running"], 1)
        self.assertEqual(s["blocked"], 1)


if __name__ == "__main__":
    unittest.main()
