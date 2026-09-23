from __future__ import absolute_import

import json
import unittest
import uuid

from fabos_core.application import FabOSApplication


class ProductionAutomationTests(unittest.TestCase):
    @staticmethod
    def _cleanup_print_job_fixture(conn, job_id, spool_id):
        # The production schema has multiple print-job dependents. Discover them
        # from SQLite metadata so this regression test stays valid as new audit/
        # manufacturing tables are added instead of relying on a brittle order.
        for _ in range(5):
            deleted = False
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            for row in tables:
                table = row[0]
                if table == "print_jobs":
                    continue
                try:
                    foreign_keys = conn.execute(
                        "PRAGMA foreign_key_list(%s)" % table
                    ).fetchall()
                except Exception:
                    continue
                for fk in foreign_keys:
                    # PRAGMA columns: id, seq, table, from, to, ...
                    if fk[2] != "print_jobs":
                        continue
                    try:
                        cursor = conn.execute(
                            'DELETE FROM "%s" WHERE "%s"=?' % (table.replace('"', '""'), fk[3].replace('"', '""')),
                            (job_id,),
                        )
                        deleted = deleted or cursor.rowcount > 0
                    except Exception:
                        # A child may itself have dependents; another pass can
                        # remove those children first.
                        continue
            try:
                conn.execute("DELETE FROM print_jobs WHERE id=?", (job_id,))
                deleted = True
            except Exception:
                pass
            if deleted:
                try:
                    conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                except Exception:
                    pass
            if not deleted:
                break
        conn.commit()

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
                self._cleanup_print_job_fixture(conn, job_id, spool_id)
                conn.execute("""INSERT INTO filament_spools
                    (id,material,color,initial_g,remaining_g,active,created_at)
                    VALUES(?,?,?,?,?,1,CURRENT_TIMESTAMP)""",
                    (spool_id, "PLA", "Green", 100.0, 100.0))
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
                self._cleanup_print_job_fixture(conn, job_id, spool_id)
        finally:
            close = getattr(app, "close", None)
            if callable(close):
                close()


    def test_printer_assignment_rejects_build_volume_mismatch(self):
        app = FabOSApplication()
        try:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM printers")
                small_id, large_id = str(uuid.uuid4()), str(uuid.uuid4())
                conn.execute("""INSERT INTO printers
                    (id,name,model,status,build_x_mm,build_y_mm,build_z_mm,total_hours)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (small_id, "Small", "Test", "idle", 100, 100, 100, 0))
                conn.execute("""INSERT INTO printers
                    (id,name,model,status,build_x_mm,build_y_mm,build_z_mm,total_hours)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (large_id, "Large", "Test", "idle", 200, 200, 200, 100))
                conn.execute("""INSERT INTO print_jobs
                    (id,status,estimated_filament_g,slicer_metadata_json)
                    VALUES(?,?,?,?)""",
                    ("dimension-test-job", "queued", 10,
                     json.dumps({"dimensions": {"x": 150, "y": 150, "z": 50}})))
                conn.commit()
                job = conn.execute("SELECT * FROM print_jobs WHERE id=?", ("dimension-test-job",)).fetchone()
            selected = app.production_automation._choose_printer(job)
            self.assertEqual(selected["id"], large_id)
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM print_jobs WHERE id=?", ("dimension-test-job",))
                conn.execute("DELETE FROM printers WHERE name IN ('Small','Large')")
                conn.commit()

    def test_spool_reservation_prevents_overcommit_within_automation_pass(self):
        app = FabOSApplication()
        try:
            spool_id = "reservation-test-spool"
            with app.database.connect() as conn:
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.execute("""INSERT INTO filament_spools
                    (id,material,color,initial_g,remaining_g,active)
                    VALUES(?,?,?,?,?,1)""",
                    (spool_id, "PLA", "Green", 100, 100))
                conn.commit()
                conn.execute("""INSERT INTO print_jobs
                    (id,status,estimated_filament_g)
                    VALUES(?,?,?)""", ("reservation-job-1", "queued", 60))
                conn.execute("""INSERT INTO print_jobs
                    (id,status,estimated_filament_g)
                    VALUES(?,?,?)""", ("reservation-job-2", "queued", 60))
                conn.commit()
                jobs = conn.execute(
                    "SELECT * FROM print_jobs WHERE id IN (?,?) ORDER BY id",
                    ("reservation-job-1", "reservation-job-2")
                ).fetchall()
            reserved = {}
            first = app.production_automation._choose_spool(jobs[0], reserved)
            self.assertEqual(first["id"], spool_id)
            reserved[spool_id] = 60
            second = app.production_automation._choose_spool(jobs[1], reserved)
            self.assertIsNone(second)
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM print_jobs WHERE id IN (?,?)",
                             ("reservation-job-1", "reservation-job-2"))
                conn.execute("DELETE FROM filament_spools WHERE id=?", ("reservation-test-spool",))
                conn.commit()

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
