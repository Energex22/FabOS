from __future__ import absolute_import

import unittest

from fabos_core.application import FabOSApplication


class StartupWiringTests(unittest.TestCase):
    def test_application_exposes_queue_services(self):
        app = FabOSApplication()
        try:
            self.assertIsNotNone(app.production_queue_planner)
            self.assertIsNotNone(app.production_queue_decision)
            self.assertIsNotNone(app.production_next_action)
        finally:
            close = getattr(app, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    unittest.main()
