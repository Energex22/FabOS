from __future__ import absolute_import

import unittest

from fabos_core.application import FabOSApplication


class Pass13StartupTests(unittest.TestCase):
    def test_action_board_is_wired(self):
        app = FabOSApplication()
        try:
            self.assertIsNotNone(app.production_action_board)
        finally:
            close = getattr(app, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    unittest.main()
