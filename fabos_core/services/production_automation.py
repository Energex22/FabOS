import os
import threading
import time
import uuid
from datetime import datetime


class ProductionAutomationService:
    """Safe, idempotent production workflow automation.

    Automatic resource assignment is enabled by default. Starting a physical
    printer is opt-in through shop settings; the default automation never
    sends a START command to real hardware.
    """

    DEFAULT_INTERVAL = 10

    def __init__(self, app):
        self.app = app
        self.db = app.database
        self._lock = threading.Lock()
        self._last = None

    def _setting_bool(self, key, default=False):
        value = str(self.app.shop_settings.get(key, "true" if default else "false") or "").strip().lower()
        return value in ("1", "true", "yes", "on")

    def _choose_spool(self, job):
        material = str(job["material"] or "").strip().lower() if "material" in job.keys() else ""
        color = str(job["color"] or "").strip().lower() if "color" in job.keys() else ""
        needed = float(job["estimated_filament_g"] or 0)
        with self.db.connect() as c:
            rows = c.execute(
                """SELECT * FROM filament_spools
                   WHERE active=1 AND remaining_g>=?
                   ORDER BY CASE WHEN lower(COALESCE(material,''))=? THEN 0 ELSE 1 END,
                            CASE WHEN lower(COALESCE(color,''))=? THEN 0 ELSE 1 END,
                            remaining_g ASC, created_at ASC""",
                (needed, material, color),
            ).fetchall()
        if not rows:
            return None
        # Never silently assign a different material when the order explicitly
        # requested one. Color is a preference because many products permit it.
        if material and str(rows[0]["material"] or "").strip().lower() != material:
            return None
        return rows[0]

    def _choose_printer(self, job):
        with self.db.connect() as c:
            rows = c.execute(
                """SELECT p.* FROM printers p
                   WHERE lower(COALESCE(p.status,'')) IN ('idle','online','operational')
                     AND NOT EXISTS (
                       SELECT 1 FROM print_jobs j
                       WHERE j.printer_id=p.id AND j.status IN ('scheduled','printing','paused')
                     )
                   ORDER BY p.total_hours ASC, p.name ASC"""
            ).fetchall()
        if not rows:
            return None
        return rows[0]

    def _assign_resources(self, job):
        if not self._setting_bool("production_auto_assign", True):
            return False
        if job["printer_id"] and job["spool_id"]:
            return False
        printer = self._choose_printer(job) if not job["printer_id"] else None
        spool = self._choose_spool(job) if not job["spool_id"] else None
        printer_id = job["printer_id"] or (printer["id"] if printer else None)
        spool_id = job["spool_id"] or (spool["id"] if spool else None)
        if printer_id == job["printer_id"] and spool_id == job["spool_id"]:
            return False
        self.app.production.assign(job["id"], printer_id, spool_id)
        self.app.operations.log(
            "production.auto_assigned",
            "Production resources assigned",
            "%s • printer %s • filament %s" % (
                job["product_name"] or "Custom job",
                printer["name"] if printer else "existing",
                "%s %s" % (spool["material"], spool["color"] or "") if spool else "existing",
            ),
            "Production",
            job["id"],
        )
        return True

    def _start_job(self, job):
        if not self._setting_bool("production_auto_start", False):
            return False
        readiness = self.app.production.job_print_readiness(job["id"], self.app.design_vault)
        if not readiness.get("ready"):
            return False
        with self.db.connect() as c:
            printer = c.execute("SELECT * FROM printers WHERE id=?", (job["printer_id"],)).fetchone()
        if not printer:
            return False
        mode = str(printer["connection_mode"] or "").lower()
        if mode == "simulation":
            self.app.printer_automation.start_simulation(printer["id"], job["id"])
            return True
        if mode in ("octoprint", "physical"):
            gcode = readiness.get("gcode")
            if not gcode:
                return False
            self.app.octoprint_print.prepare_and_start(printer, gcode)
            self.app.production.set_status(job["id"], "printing")
            return True
        return False

    def tick(self):
        """Run one deterministic automation pass and return an audit summary."""
        if not self._lock.acquire(False):
            return {"skipped": True, "reason": "automation pass already running"}
        try:
            created = self.app.production.create_jobs_for_all_new_orders()
            assigned = 0
            started = 0
            with self.db.connect() as c:
                jobs = c.execute(
                    """SELECT j.*,
                              COALESCE((
                                  SELECT qi.material
                                  FROM quote_items qi
                                  WHERE qi.quote_id=o.quote_id
                                    AND qi.product_id=j.product_id
                                    AND (qi.variant_id=j.variant_id
                                         OR (qi.variant_id IS NULL AND j.variant_id IS NULL))
                                  ORDER BY qi.rowid
                                  LIMIT 1
                              ),'') material,
                              COALESCE((
                                  SELECT qi.color
                                  FROM quote_items qi
                                  WHERE qi.quote_id=o.quote_id
                                    AND qi.product_id=j.product_id
                                    AND (qi.variant_id=j.variant_id
                                         OR (qi.variant_id IS NULL AND j.variant_id IS NULL))
                                  ORDER BY qi.rowid
                                  LIMIT 1
                              ),'') color,
                              COALESCE(p.name,'Custom Job') product_name
                       FROM print_jobs j
                       LEFT JOIN orders o ON o.id=j.order_id
                       LEFT JOIN products p ON p.id=j.product_id
                       WHERE j.status IN ('queued','scheduled')
                       ORDER BY CASE WHEN o.due_at IS NULL THEN 1 ELSE 0 END,
                                o.due_at, j.created_at"""
                ).fetchall()
            for job in jobs:
                try:
                    if self._assign_resources(job):
                        assigned += 1
                    refreshed = self.app.production.get(job["id"])
                    if refreshed["printer_id"] and refreshed["spool_id"]:
                        if self._start_job(refreshed):
                            started += 1
                except Exception as exc:
                    try:
                        self.app.error_log.error(
                            "Production automation pass encountered an error",
                            "%s: %s" % (job["id"], exc),
                        )
                    except Exception:
                        pass
            try:
                self.app.operations.reconcile_workflows()
                self.app.operations.refresh_notifications()
            except Exception:
                pass
            result = {
                "created_jobs": int(created or 0),
                "assigned_jobs": assigned,
                "started_jobs": started,
                "timestamp": datetime.now().isoformat(timespec="seconds"),
            }
            self._last = result
            return result
        finally:
            self._lock.release()

    def start_worker(self):
        if not self._setting_bool("production_automation_enabled", True):
            return None
        if os.environ.get("FABOS_DISABLE_AUTOMATION", "").strip().lower() in ("1", "true", "yes"):
            return None
        interval = int(float(self.app.shop_settings.get(
            "production_automation_interval_seconds", self.DEFAULT_INTERVAL
        ) or self.DEFAULT_INTERVAL))
        interval = max(3, min(interval, 300))

        def worker():
            while True:
                try:
                    self.tick()
                except Exception as exc:
                    try:
                        self.app.error_log.error("Production automation worker failed", str(exc))
                    except Exception:
                        pass
                time.sleep(interval)

        thread = threading.Thread(target=worker, name="FabOSProductionAutomation", daemon=True)
        thread.start()
        return thread

    @property
    def last_run(self):
        return dict(self._last or {})
