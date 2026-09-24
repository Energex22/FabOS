import json
import math
import os
import threading
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
        self._worker_thread = None
        self._stop_event = threading.Event()

    def _setting_bool(self, key, default=False):
        value = str(self.app.shop_settings.get(key, "true" if default else "false") or "").strip().lower()
        return value in ("1", "true", "yes", "on")

    def _job_dimensions(self, job):
        """Return required X/Y/Z dimensions when slicer metadata provides them."""
        raw = job["slicer_metadata_json"] if "slicer_metadata_json" in job.keys() else None
        if not raw:
            return None
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        candidates = data.get("dimensions") or data.get("size") or data.get("bounds")
        if not isinstance(candidates, dict):
            return None
        values = []
        for key in ("x", "y", "z"):
            value = candidates.get(key, candidates.get(key.upper()))
            try:
                value = float(value)
            except (TypeError, ValueError):
                return None
            if not math.isfinite(value) or value <= 0:
                return None
            values.append(value)
        return tuple(values)

    def _printer_supports_job(self, printer, job):
        """Apply only capability data FabOS actually stores."""
        dimensions = self._job_dimensions(job)
        if not dimensions:
            return True
        limits = []
        for key in ("build_x_mm", "build_y_mm", "build_z_mm"):
            try:
                value = float(printer[key])
            except (TypeError, ValueError):
                return True
            if value <= 0:
                return True
            limits.append(value)
        x, y, z = dimensions
        return ((x <= limits[0] and y <= limits[1] and z <= limits[2]) or
                (y <= limits[0] and x <= limits[1] and z <= limits[2]))

    def _choose_spool(self, job, reserved_grams=None):
        material = str(job["material"] or "").strip().lower() if "material" in job.keys() else ""
        color = str(job["color"] or "").strip().lower() if "color" in job.keys() else ""
        needed = float(job["estimated_filament_g"] or 0)
        reserved_grams = reserved_grams or {}
        with self.db.connect() as c:
            rows = c.execute(
                """SELECT fs.*,
                          COALESCE((
                              SELECT SUM(COALESCE(j.estimated_filament_g,0))
                              FROM print_jobs j
                              WHERE j.spool_id=fs.id
                                AND j.status IN ('queued','scheduled','printing','paused')
                          ),0) committed_g
                   FROM filament_spools fs
                   WHERE fs.active=1
                     AND fs.remaining_g>=?
                     AND (?='' OR lower(COALESCE(fs.material,''))=?)
                   ORDER BY CASE WHEN lower(COALESCE(fs.material,''))=? THEN 0 ELSE 1 END,
                            CASE WHEN lower(COALESCE(fs.color,''))=? THEN 0 ELSE 1 END,
                            fs.remaining_g ASC, fs.created_at ASC""",
                (needed, material, material, material, color),
            ).fetchall()
        rows = [
            r for r in rows
            if float(r["remaining_g"] or 0)
            - float(r["committed_g"] or 0)
            - float(reserved_grams.get(r["id"], 0)) >= needed
        ]
        if not rows:
            return None
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
                       WHERE j.printer_id=p.id AND j.status IN ('queued','scheduled','printing','paused')
                     )
                   ORDER BY p.total_hours ASC, p.name ASC"""
            ).fetchall()
        rows = [r for r in rows if self._printer_supports_job(r, job)]
        if not rows:
            return None
        return rows[0]

    def _assign_resources(self, job, reserved_grams=None):
        if not self._setting_bool("production_auto_assign", True):
            return False
        if job["printer_id"] and job["spool_id"]:
            return False
        printer = self._choose_printer(job) if not job["printer_id"] else None
        spool = self._choose_spool(job, reserved_grams) if not job["spool_id"] else None
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
            reserved_grams = {}
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
                    if self._assign_resources(job, reserved_grams):
                        assigned += 1
                        if not job["spool_id"]:
                            assigned_job = self.app.production.get(job["id"])
                            if assigned_job["spool_id"]:
                                spool_id = assigned_job["spool_id"]
                                reserved_grams[spool_id] = (
                                    reserved_grams.get(spool_id, 0) +
                                    float(assigned_job["estimated_filament_g"] or 0)
                                )
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
                        self.app.operations._upsert_notification(
                            "event:automation:error:%s" % job["id"],
                            "high",
                            "Production automation needs attention",
                            "Job %s could not be processed automatically: %s" % (job["id"], exc),
                            "Production",
                            job["id"],
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

    def _worker_interval(self):
        try:
            interval = float(self.app.shop_settings.get(
                "production_automation_interval_seconds", self.DEFAULT_INTERVAL
            ) or self.DEFAULT_INTERVAL)
        except (TypeError, ValueError):
            interval = self.DEFAULT_INTERVAL
        if not math.isfinite(interval):
            interval = self.DEFAULT_INTERVAL
        return max(3, min(int(interval), 300))

    def start_worker(self):
        if not self._setting_bool("production_automation_enabled", True):
            return None
        if os.environ.get("FABOS_DISABLE_AUTOMATION", "").strip().lower() in ("1", "true", "yes"):
            return None
        with self._lock:
            if self._worker_thread is not None and self._worker_thread.is_alive():
                return self._worker_thread
            self._stop_event.clear()
            interval = self._worker_interval()

            def worker():
                while not self._stop_event.is_set():
                    try:
                        self.tick()
                    except Exception as exc:
                        try:
                            self.app.error_log.error("Production automation worker failed", str(exc))
                        except Exception:
                            pass
                    self._stop_event.wait(interval)

            thread = threading.Thread(target=worker, name="FabOSProductionAutomation", daemon=True)
            self._worker_thread = thread
            thread.start()
            return thread

    def stop_worker(self, timeout=5):
        with self._lock:
            thread = self._worker_thread
            self._stop_event.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(max(0, timeout))
        with self._lock:
            if self._worker_thread is thread and (thread is None or not thread.is_alive()):
                self._worker_thread = None
        return thread is not None and not thread.is_alive()

    @property
    def last_run(self):
        return dict(self._last or {})
