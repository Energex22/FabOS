from __future__ import absolute_import

import unittest

from fabos_core.services.production_action_board import ProductionActionBoard


class Production(object):
    def list_jobs(self):
        return [
            {"id": "1", "status": "printing", "printer_id": "p1"},
            {"id": "2", "status": "queued"},
        ]


class NextAction(object):
    def for_job(self, job):
        if job["id"] == "1":
            return {
                "action": "monitor",
                "label": "Monitor active print",
                "safe_to_start": False,
                "reason": "active",
                "blockers": [],
                "warnings": [],
            }
        return {
            "action": "assign_printer",
            "label": "Assign printer",
            "safe_to_start": False,
            "reason": "missing printer",
            "blockers": [],
            "warnings": [],
        }


class App(object):
    def __init__(self):
        self.production = Production()
        self.production_next_action = NextAction()


class ProductionActionBoardTests(unittest.TestCase):
    def test_build(self):
        board = ProductionActionBoard(App()).build()
        self.assertEqual(board["counts"]["total"], 2)
        self.assertEqual(board["counts"]["monitor"], 1)
        self.assertEqual(board["counts"]["assign_printer"], 1)
        self.assertFalse(board["rows"][0]["safe_to_start"])

    def test_explicit_jobs(self):
        board = ProductionActionBoard(App()).build([{"id": "9", "status": "queued"}])
        self.assertEqual(board["rows"][0]["job_id"], "9")


if __name__ == "__main__":
    unittest.main()
