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

    def test_completed_job_consumes_assigned_filament_once(self):
        app = FabOSApplication()
        try:
            with app.database.connect() as conn:
                spool_id = "automation-test-spool"
                job_id = "automation-test-job"
                conn.execute("DELETE FROM print_jobs WHERE id=?", (job_id,))
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.execute("""INSERT INTO filament_spools
                    (id,material,color,remaining_g,active,created_at)
                    VALUES(?,?,?,?,1,CURRENT_TIMESTAMP)""",
                    (spool_id, "PLA", "Green", 100.0))
                conn.execute("""INSERT INTO print_jobs
                    (id,status,spool_id,estimated_filament_g,actual_filament_g)
                    VALUES(?,?,?,?,?)""",
                    (job_id, "printing", spool_id, 20.0, 20.0))
                conn.commit()
            app.production.set_status(job_id, "completed")
            with app.database.connect() as conn:
                remaining = conn.execute("SELECT remaining_g FROM filament_spools WHERE id=?", (spool_id,)).fetchone()[0]
                deducted = conn.execute("SELECT filament_deducted FROM print_jobs WHERE id=?", (job_id,)).fetchone()[0]
            self.assertAlmostEqual(float(remaining), 80.0, places=4)
            self.assertEqual(int(deducted), 1)
            with app.database.connect() as conn:
                conn.execute("DELETE FROM print_jobs WHERE id=?", (job_id,))
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.commit()
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
                app.shop_settings.set_validated("production_automation_interval_seconds", "-1")
        finally:
            close = getattr(app, "close", None)
            if callable(close):
                close()


if __name__ == "__main__":
    unittest.main()
