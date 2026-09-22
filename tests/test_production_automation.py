from __future__ import absolute_import

import unittest

from fabos_core.application import FabOSApplication


class ProductionAutomationTests(unittest.TestCase):
    def test_application_wires_automation_without_starting_worker(self):
        app = FabOSApplication()
        try:
            self.assertIsNotNone(app.production_automation)
            self.assertEqual(app.shop_settings.get("production_automation_enabled"), "true")
            self.assertEqual(app.shop_settings.get("production_auto_assign"), "true")
            self.assertEqual(app.shop_settings.get("production_auto_start"), "false")
        finally:
            close = getattr(app, "close", None)
            if callable(close):
                close()

    def test_automation_settings_are_validated(self):
        app = FabOSApplication()
        try:
            app.shop_settings.set_validated("production_auto_start", "true")
            self.assertEqual(app.shop_settings.get("production_auto_start"), "true")
            with self.assertRaises(ValueError):
                app.shop_settings.set_validated("production_automation_interval_seconds", "2")
        finally:
            close = getattr(app, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    unittest.main()
