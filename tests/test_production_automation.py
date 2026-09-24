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
                    if fk[2] != "print_jobs":
                        continue
                    try:
                        cursor = conn.execute(
                            'DELETE FROM "%s" WHERE "%s"=?' % (table.replace('"', '""'), fk[3].replace('"', '""')),
                            (job_id,),
                        )
                        deleted = deleted or cursor.rowcount > 0
                    except Exception:
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

    def test_printer_assignment_skips_unavailable_statuses(self):
        app = FabOSApplication()
        try:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM printers")
                offline_id, maintenance_id, idle_id = [str(uuid.uuid4()) for _ in range(3)]
                for pid, name, status, hours in (
                    (offline_id, "Offline", "offline", 0),
                    (maintenance_id, "Maintenance", "maintenance", 0),
                    (idle_id, "Idle", "idle", 10),
                ):
                    conn.execute("""INSERT INTO printers
                        (id,name,model,status,total_hours)
                        VALUES(?,?,?,?,?)""",
                        (pid, name, "Test", status, hours))
                conn.execute("""INSERT INTO print_jobs
                    (id,status,estimated_filament_g)
                    VALUES(?,?,?)""",
                    ("status-test-job", "queued", 10))
                conn.commit()
                job = conn.execute("SELECT * FROM print_jobs WHERE id=?", ("status-test-job",)).fetchone()
            selected = app.production_automation._choose_printer(job)
            self.assertEqual(selected["id"], idle_id)
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM print_jobs WHERE id=?", ("status-test-job",))
                conn.execute("DELETE FROM printers WHERE name IN ('Offline','Maintenance','Idle')")
                conn.commit()

    def test_invalid_job_dimensions_do_not_create_false_capability_match(self):
        app = FabOSApplication()
        with app.database.connect() as conn:
            job = conn.execute(
                "SELECT * FROM print_jobs WHERE id=?",
                ("dimension-invalid-test-job",),
            ).fetchone()
            if job:
                conn.execute("DELETE FROM print_jobs WHERE id=?", ("dimension-invalid-test-job",))
            conn.execute(
                "INSERT INTO print_jobs(id,status,estimated_filament_g,slicer_metadata_json) VALUES(?,?,?,?)",
                ("dimension-invalid-test-job", "queued", 10,
                 json.dumps({"dimensions": {"x": -1, "y": 20, "z": 20}})),
            )
            conn.commit()
            job = conn.execute(
                "SELECT * FROM print_jobs WHERE id=?",
                ("dimension-invalid-test-job",),
            ).fetchone()
        try:
            self.assertIsNone(app.production_automation._job_dimensions(job))
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM print_jobs WHERE id=?", ("dimension-invalid-test-job",))
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

    def test_explicit_material_selects_matching_spool_even_when_mismatch_sorts_first(self):
        app = FabOSApplication()
        matching_id = str(uuid.uuid4())
        mismatch_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (mismatch_id, "PETG", "Green", 100, 100),
                )
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (matching_id, "PLA", "Green", 100, 100),
                )
                conn.commit()
            job = {"material": "PLA", "color": "", "estimated_filament_g": 20}
            selected = app.production_automation._choose_spool(job)
            self.assertEqual(selected["id"], matching_id)
            self.assertEqual(str(selected["material"]).lower(), "pla")
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM filament_spools WHERE id IN (?,?)", (matching_id, mismatch_id))
                conn.commit()

    def test_explicit_material_mismatch_is_never_auto_assigned(self):
        app = FabOSApplication()
        spool_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (spool_id, "PETG", "Green", 100, 100),
                )
                conn.commit()
            # Material is derived from quote data during the automation query;
            # exercise the selector directly without inventing a print_jobs column.
            job = {"material": "PLA", "color": "", "estimated_filament_g": 20}
            self.assertIsNone(app.production_automation._choose_spool(job))
        finally:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, job_id, spool_id)


    def test_reprint_requeues_without_stale_resources(self):
        app = FabOSApplication()
        app.production_automation.stop_worker()
        job_id = str(uuid.uuid4())
        printer_id = str(uuid.uuid4())
        spool_id = str(uuid.uuid4())
        new_job_id = None
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO printers(id,name,model,status,build_x_mm,build_y_mm,build_z_mm,total_hours) VALUES(?,?,?,?,?,?,?,?)",
                    (printer_id, "Reprint Test Printer", "Test", "idle", 200, 200, 200, 0),
                )
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (spool_id, "PLA", "Green", 100, 100),
                )
                conn.execute(
                    """INSERT INTO print_jobs
                    (id,printer_id,spool_id,status,gcode_path,estimated_minutes,estimated_filament_g)
                    VALUES(?,?,?,?,?,?,?)""",
                    (job_id, printer_id, spool_id, "failed", "test.gcode", 20, 20),
                )
                conn.commit()
            new_job_id = app.manufacturing.reprint(job_id)
            with app.database.connect() as conn:
                row = conn.execute(
                    "SELECT status,printer_id,spool_id FROM print_jobs WHERE id=?",
                    (new_job_id,),
                ).fetchone()
            self.assertEqual(row["status"], "queued")
            self.assertIsNone(row["printer_id"])
            self.assertIsNone(row["spool_id"])
        finally:
            with app.database.connect() as conn:
                if new_job_id:
                    self._cleanup_print_job_fixture(conn, new_job_id, None)
                self._cleanup_print_job_fixture(conn, job_id, spool_id)
                conn.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                conn.commit()

    def test_completed_print_accounting_failure_creates_notification(self):
        app = FabOSApplication()
        job_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO print_jobs(id,status,estimated_filament_g) VALUES(?,?,?)",
                    (job_id, "printing", 20),
                )
                conn.commit()
            from unittest.mock import patch
            with patch(
                "fabos_core.services.manufacturing.ManufacturingService.complete_with_inventory",
                side_effect=RuntimeError("inventory failure"),
            ):
                app.production.set_status(job_id, "completed")
            with app.database.connect() as conn:
                row = conn.execute(
                    "SELECT severity,title,body FROM notifications WHERE dedupe_key=?",
                    ("event:production:completed:%s" % job_id,),
                ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["severity"], "high")
            self.assertIn("inventory failure", row["body"])
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM notifications WHERE dedupe_key=?", ("event:production:completed:%s" % job_id,))
                conn.execute("DELETE FROM print_jobs WHERE id=?", (job_id,))
                conn.commit()

    def test_failed_print_records_filament_waste_once(self):
        app = FabOSApplication()
        spool_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (spool_id, "PLA", "Green", 100, 100),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,spool_id,status,estimated_filament_g) VALUES(?,?,?,?)",
                    (job_id, spool_id, "printing", 40),
                )
                conn.commit()
            app.production.set_status(job_id, "failed")
            with app.database.connect() as conn:
                remaining = conn.execute("SELECT remaining_g FROM filament_spools WHERE id=?", (spool_id,)).fetchone()[0]
                waste = conn.execute(
                    "SELECT COUNT(*) FROM inventory_transactions WHERE reference_type='failed_print' AND reference_id=? AND transaction_type='waste'",
                    (job_id,),
                ).fetchone()[0]
            self.assertEqual(remaining, 80.0)
            self.assertEqual(waste, 1)
            app.production.set_status(job_id, "failed")
            with app.database.connect() as conn:
                self.assertEqual(conn.execute("SELECT remaining_g FROM filament_spools WHERE id=?", (spool_id,)).fetchone()[0], 80.0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM inventory_transactions WHERE reference_type='failed_print' AND reference_id=?", (job_id,)).fetchone()[0], 1)
        finally:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, job_id, spool_id)

    def test_physical_start_claims_job_before_hardware_command(self):
        from unittest.mock import patch

        app = FabOSApplication()
        job_id = str(uuid.uuid4())
        printer_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO printers(id,name,status,connection_mode) VALUES(?,?,?,?)",
                    (printer_id, "Physical Claim Test", "idle", "octoprint"),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,status,printer_id,estimated_filament_g) VALUES(?,?,?,?)",
                    (job_id, "scheduled", printer_id, 10),
                )
                conn.commit()
                job = conn.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()

            events = []
            def claim(job_id_arg, status):
                events.append(("status", status))
                app.production.set_status(job_id_arg, status)

            def start(*args, **kwargs):
                events.append(("hardware", None))
                raise RuntimeError("printer start verification failed")

            with patch.object(app.production, "job_print_readiness", return_value={"ready": True, "gcode": "test.gcode"}),                  patch.object(app.production, "set_status", side_effect=claim),                  patch.object(app.octoprint_print, "prepare_and_start", side_effect=start):
                with self.assertRaises(RuntimeError):
                    app.production_automation._start_job(job)

            self.assertEqual(events, [("status", "printing"), ("hardware", None)])
            with app.database.connect() as conn:
                state = conn.execute("SELECT status FROM print_jobs WHERE id=?", (job_id,)).fetchone()[0]
            self.assertEqual(state, "printing")
        finally:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, job_id, None)
                conn.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                conn.commit()
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

    def test_spool_assignment_accounts_for_existing_committed_jobs(self):
        app = FabOSApplication()
        spool = str(uuid.uuid4())
        first = str(uuid.uuid4())
        second = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (spool, "PLA", "Green", 100, 100),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,spool_id,status,estimated_filament_g) VALUES(?,?,?,?)",
                    (first, spool, "scheduled", 60),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,status,estimated_filament_g) VALUES(?,?,?)",
                    (second, "queued", 60),
                )
                conn.commit()
                job = conn.execute("SELECT * FROM print_jobs WHERE id=?", (second,)).fetchone()
            self.assertIsNone(app.production_automation._choose_spool(job))
        finally:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, first, spool)
                conn.execute("DELETE FROM print_jobs WHERE id=?", (second,))
                conn.commit()


    def test_printer_assignment_does_not_overcommit_queued_jobs(self):
        app = FabOSApplication()
        printer_id = str(uuid.uuid4())
        first_id = str(uuid.uuid4())
        second_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM printers")
                conn.execute(
                    "INSERT INTO printers(id,name,model,status,total_hours) VALUES(?,?,?,?,?)",
                    (printer_id, "Queue Guard", "Test", "idle", 0),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,printer_id,status,estimated_filament_g) VALUES(?,?,?,?)",
                    (first_id, printer_id, "queued", 10),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,status,estimated_filament_g) VALUES(?,?,?)",
                    (second_id, "queued", 10),
                )
                conn.commit()
                second = conn.execute("SELECT * FROM print_jobs WHERE id=?", (second_id,)).fetchone()
            self.assertIsNone(app.production_automation._choose_printer(second))
        finally:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, first_id, None)
                self._cleanup_print_job_fixture(conn, second_id, None)
                conn.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                conn.commit()


    def test_completion_surfaces_inventory_accounting_failure(self):
        app = FabOSApplication()
        job_id = str(uuid.uuid4())
        try:
            spool_id = str(uuid.uuid4())
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (spool_id, "PLA", "Green", 100, 100),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,status,spool_id,estimated_filament_g) VALUES(?,?,?,?)",
                    (job_id, "printing", spool_id, 40),
                )
                conn.commit()
            from unittest.mock import patch
            from fabos_core.services.inventory_profit import InventoryProfitService
            from fabos_core.services.manufacturing import ManufacturingService
            with patch.object(InventoryProfitService, "record_consumption", side_effect=RuntimeError("inventory write failed")):
                ManufacturingService(app.database).complete_with_inventory(job_id)
            with app.database.connect() as conn:
                note = conn.execute(
                    "SELECT COUNT(*) FROM notifications WHERE dedupe_key=?",
                    ("inventory:completion:" + job_id,),
                ).fetchone()[0]
                deducted = conn.execute(
                    "SELECT filament_deducted FROM print_jobs WHERE id=?", (job_id,)
                ).fetchone()[0]
            self.assertEqual(note, 1)
            self.assertEqual(deducted, 0)
        finally:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, job_id, spool_id)
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.execute("DELETE FROM notifications WHERE dedupe_key=?", ("inventory:completion:" + job_id,))
                conn.commit()

    def test_fulfillment_update_preserves_existing_shipping_cost_when_omitted(self):
        from fabos_core.services.fulfillment import FulfillmentService

        app = FabOSApplication()
        order_id = str(uuid.uuid4())
        invoice_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO orders(id,order_number,status) VALUES(?,?,?)",
                    (order_id, "FULFILL-SAFETY-" + order_id[:8], "ready"),
                )
                conn.execute(
                    """INSERT INTO invoices(
                        id,invoice_number,order_id,status,subtotal_cents,tax_cents,
                        discount_cents,paid_cents,total_cents,shipping_cents
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                    (invoice_id, "INV-SAFETY-" + invoice_id[:8], order_id, "open",
                     1000, 0, 0, 0, 1000, 0),
                )
                conn.commit()

            service = FulfillmentService(app.database)
            fid = service.save(order_id, "shipping", "packed", shipping_cost_cents=500)
            service.save(order_id, "shipping", "shipped")

            with app.database.connect() as conn:
                fulfillment = conn.execute(
                    "SELECT shipping_cost_cents FROM fulfillments WHERE id=?", (fid,)
                ).fetchone()
                invoice = conn.execute(
                    "SELECT shipping_cents,total_cents FROM invoices WHERE id=?", (invoice_id,)
                ).fetchone()

            self.assertEqual(int(fulfillment["shipping_cost_cents"]), 500)
            self.assertEqual(int(invoice["shipping_cents"]), 500)
            self.assertEqual(int(invoice["total_cents"]), 1500)
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM invoices WHERE id=?", (invoice_id,))
                conn.execute("DELETE FROM fulfillments WHERE order_id=?", (order_id,))
                conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
                conn.commit()
            close = getattr(app, "close", None)
            if callable(close):
                close()

    def test_manual_assignment_rejects_occupied_printer_and_overcommitted_spool(self):
        app = FabOSApplication()
        printer_id, spool_id = str(uuid.uuid4()), str(uuid.uuid4())
        blocker_id, job_id = str(uuid.uuid4()), str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "DELETE FROM printers"
                )
                conn.execute(
                    "INSERT INTO printers(id,name,model,status) VALUES(?,?,?,?)",
                    (printer_id, "Manual Guard", "Test", "idle"),
                )
                conn.execute(
                    """INSERT INTO filament_spools
                       (id,material,color,initial_g,remaining_g,active)
                       VALUES(?,?,?,?,?,1)""",
                    (spool_id, "PLA", "Green", 100, 100),
                )
                conn.execute(
                    """INSERT INTO print_jobs
                       (id,printer_id,spool_id,status,estimated_filament_g)
                       VALUES(?,?,?,?,?)""",
                    (blocker_id, printer_id, spool_id, "queued", 60),
                )
                conn.execute(
                    "INSERT INTO print_jobs(id,status,estimated_filament_g) VALUES(?,?,?)",
                    (job_id, "queued", 60),
                )
                conn.commit()
            with self.assertRaises(ValueError):
                app.production.assign(job_id, printer_id=printer_id)
            with self.assertRaises(ValueError):
                app.production.assign(job_id, spool_id=spool_id)
        finally:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, blocker_id, spool_id)
                self._cleanup_print_job_fixture(conn, job_id, None)
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                conn.commit()
            close = getattr(app, "close", None)
            if callable(close):
                close()

    def test_qc_rework_multiple_inspections_create_one_replacement(self):
        app = FabOSApplication()
        order_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        qc_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        try:
            with app.database.connect() as conn:
                conn.execute(
                    """INSERT INTO orders(id,order_number,status,total_cents)
                       VALUES(?,?,?,?)""",
                    (order_id, "REWORK-DUP", "qc", 1000),
                )
                conn.execute(
                    """INSERT INTO print_jobs
                       (id,order_id,status,estimated_minutes,estimated_filament_g)
                       VALUES(?,?,?,?,?)""",
                    (job_id, order_id, "completed", 30, 20),
                )
                for qid in qc_ids:
                    conn.execute(
                        """INSERT INTO qc_inspections
                           (id,order_id,print_job_id,status) VALUES(?,?,?,'rework')""",
                        (qid, order_id, job_id),
                    )
                conn.commit()
            app.operations.reconcile_workflows()
            with app.database.connect() as conn:
                rows = conn.execute(
                    """SELECT id,status FROM print_jobs
                       WHERE order_id=? ORDER BY created_at""",
                    (order_id,),
                ).fetchall()
                replacements = [r for r in rows if r["id"] != job_id]
                self.assertEqual(len(replacements), 1)
                self.assertEqual(replacements[0]["status"], "queued")
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM qc_inspections WHERE order_id=?", (order_id,))
                conn.execute("DELETE FROM print_jobs WHERE order_id=?", (order_id,))
                conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
                conn.commit()
            close = getattr(app, "close", None)
            if callable(close):
                close()



    def test_manual_assignment_rejects_incompatible_material_and_offline_printer(self):
        app = FabOSApplication()
        order_id = str(uuid.uuid4())
        quote_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        quote_item_id = str(uuid.uuid4())
        printer_id = str(uuid.uuid4())
        spool_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "INSERT INTO quotes(id,quote_number,status) VALUES(?,?,?)",
                    (quote_id, "Q-ASSIGN-GUARD", "accepted"),
                )
                conn.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents,quote_id) VALUES(?,?,?,?,?)",
                    (order_id, "ASSIGN-GUARD", "in_production", 1000, quote_id),
                )
                conn.execute(
                    """INSERT INTO quote_items
                       (id,quote_id,product_id,variant_id,description,quantity,unit_price_cents,material)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (quote_item_id, quote_id, None, None, "Custom", 1, 1000, "PLA"),
                )
                conn.execute(
                    """INSERT INTO print_jobs(id,order_id,status,estimated_filament_g)
                       VALUES(?,?,?,?)""",
                    (job_id, order_id, "queued", 20),
                )
                conn.execute(
                    "INSERT INTO filament_spools(id,material,color,initial_g,remaining_g,active) VALUES(?,?,?,?,?,1)",
                    (spool_id, "PETG", "Green", 100, 100),
                )
                conn.execute(
                    "INSERT INTO printers(id,name,status) VALUES(?,?,?)",
                    (printer_id, "Offline Guard", "offline"),
                )
                conn.commit()
            with self.assertRaises(ValueError):
                app.production.assign(job_id, spool_id=spool_id)
            with self.assertRaises(ValueError):
                app.production.assign(job_id, printer_id=printer_id)
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM print_jobs WHERE id=?", (job_id,))
                conn.execute("DELETE FROM quote_items WHERE id=?", (quote_item_id,))
                conn.execute("DELETE FROM orders WHERE id=?", (order_id,))
                conn.execute("DELETE FROM quotes WHERE id=?", (quote_id,))
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                conn.commit()




    def test_manual_printer_assignment_rejects_build_volume_mismatch(self):
        app = FabOSApplication()
        job_id = "manual-dimension-test-job"
        small_id = str(uuid.uuid4())
        try:
            with app.database.connect() as conn:
                conn.execute(
                    "DELETE FROM print_jobs WHERE id=?",
                    (job_id,),
                )
                conn.execute(
                    """INSERT INTO printers
                    (id,name,model,status,build_x_mm,build_y_mm,build_z_mm,total_hours)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (small_id, "Manual Small", "Test", "idle", 100, 100, 100, 0),
                )
                conn.execute(
                    """INSERT INTO print_jobs
                    (id,status,estimated_filament_g,slicer_metadata_json)
                    VALUES(?,?,?,?)""",
                    (job_id, "queued", 10,
                     json.dumps({"dimensions": {"x": 150, "y": 80, "z": 50}})),
                )
                conn.commit()
            with self.assertRaisesRegex(ValueError, "build volume"):
                app.production.assign(job_id, small_id, None)
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM print_jobs WHERE id=?", (job_id,))
                conn.execute("DELETE FROM printers WHERE id=?", (small_id,))
                conn.commit()


    def test_filament_consumption_rejects_overdraw_without_mutation(self):
        app = FabOSApplication()
        spool_id = "overdraw-test-spool"
        job_id = "overdraw-test-job"
        try:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM inventory_transactions WHERE item_id=?", (spool_id,))
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.execute(
                    """INSERT INTO filament_spools
                    (id,material,color,remaining_g,initial_g,cost_cents,active)
                    VALUES(?,?,?,?,?,?,1)""",
                    (spool_id, "TEST-PLA", "Green", 10, 100, 2000),
                )
                conn.commit()
            with self.assertRaisesRegex(ValueError, "Insufficient filament"):
                app.inventory_profit.record_consumption(spool_id, 11, job_id)
            with app.database.connect() as conn:
                spool = conn.execute(
                    "SELECT remaining_g FROM filament_spools WHERE id=?", (spool_id,)
                ).fetchone()
                tx = conn.execute(
                    "SELECT COUNT(*) FROM inventory_transactions WHERE item_id=? AND reference_id=?",
                    (spool_id, job_id),
                ).fetchone()[0]
            self.assertEqual(float(spool["remaining_g"]), 10.0)
            self.assertEqual(tx, 0)
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM inventory_transactions WHERE item_id=?", (spool_id,))
                conn.execute("DELETE FROM filament_spools WHERE id=?", (spool_id,))
                conn.commit()


    def test_closing_job_does_not_hide_offline_printer(self):
        app = FabOSApplication()
        printer_id = "offline-close-test-printer"
        spool_id = "offline-close-test-spool"
        job_id = "offline-close-test-job"
        try:
            with app.database.connect() as conn:
                self._cleanup_print_job_fixture(conn, job_id, spool_id)
                conn.execute("DELETE FROM inventory_transactions WHERE reference_id=?", (job_id,))
                conn.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                conn.execute(
                    """INSERT INTO printers
                    (id,name,model,status,build_x_mm,build_y_mm,build_z_mm,total_hours)
                    VALUES(?,?,?,?,?,?,?,?)""",
                    (printer_id, "Offline Test", "Test", "offline", 200, 200, 200, 0),
                )
                conn.execute(
                    """INSERT INTO filament_spools
                    (id,material,color,initial_g,remaining_g,active)
                    VALUES(?,?,?,?,?,1)""",
                    (spool_id, "TEST-PLA", "Green", 100, 100),
                )
                conn.execute(
                    """INSERT INTO print_jobs
                    (id,status,printer_id,spool_id,estimated_filament_g)
                    VALUES(?,?,?,?,?)""",
                    (job_id, "printing", printer_id, spool_id, 20),
                )
                conn.commit()
            app.production.set_status(job_id, "failed")
            with app.database.connect() as conn:
                state = conn.execute("SELECT status FROM printers WHERE id=?", (printer_id,)).fetchone()[0]
            self.assertEqual(state, "offline")
        finally:
            with app.database.connect() as conn:
                conn.execute("DELETE FROM inventory_transactions WHERE reference_id=?", (job_id,))
                self._cleanup_print_job_fixture(conn, job_id, spool_id)
                conn.execute("DELETE FROM printers WHERE id=?", (printer_id,))
                conn.commit()


if __name__ == "__main__":
    unittest.main()
