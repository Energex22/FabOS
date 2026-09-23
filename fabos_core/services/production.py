import uuid
from datetime import datetime

class ProductionService:
    VALID_JOB_STATUSES={"queued","scheduled","printing","paused","completed","failed","cancelled"}
    JOB_STATUS_TRANSITIONS={
        "queued":{"queued","scheduled","printing","completed","failed","cancelled"},
        "scheduled":{"scheduled","printing","paused","completed","failed","cancelled"},
        "printing":{"printing","paused","completed","failed","cancelled"},
        "paused":{"paused","printing","completed","failed","cancelled"},
        "completed":{"completed"},
        "failed":{"failed"},
        "cancelled":{"cancelled"},
    }
    SORT_COLUMNS = {
        "job": "j.created_at",
        "order": "o.order_number",
        "product": "product_name COLLATE NOCASE",
        "printer": "printer_name COLLATE NOCASE",
        "status": "j.status",
        "estimate": "j.estimated_minutes",
        "created": "j.created_at",
    }

    def __init__(self, database, event_bus=None):
        self.database = database
        self.event_bus = event_bus

    def list_jobs(self, query="", status="All", sort_column="created", descending=True, group="all"):
        column = self.SORT_COLUMNS.get(sort_column, "j.created_at")
        direction = "DESC" if descending else "ASC"
        needle = "%%%s%%" % query.strip()
        where = ["(?='' OR COALESCE(o.order_number,'') LIKE ? OR COALESCE(p.name,'') LIKE ? OR COALESCE(pr.name,'') LIKE ?)"]
        args = [query.strip(), needle, needle, needle]
        if group=="active":
            where.append("j.status NOT IN ('completed','cancelled')")
        elif group=="history":
            where.append("j.status IN ('completed','cancelled')")
        if status and status != "All":
            where.append("j.status=?")
            args.append(status.lower())
        sql = """
            SELECT j.*, COALESCE(o.order_number,'—') order_number,
                   COALESCE(p.name,'Custom Job') product_name,
                   COALESCE(pr.name,'Unassigned') printer_name,
                   COALESCE(c.name,'No customer') customer_name,
                   COALESCE(fs.material || ' ' || COALESCE(fs.color,''),'Not selected') spool_name
            FROM print_jobs j
            LEFT JOIN orders o ON o.id=j.order_id
            LEFT JOIN customers c ON c.id=o.customer_id
            LEFT JOIN products p ON p.id=j.product_id
            LEFT JOIN printers pr ON pr.id=j.printer_id
            LEFT JOIN filament_spools fs ON fs.id=j.spool_id
            WHERE %s
            ORDER BY %s %s
        """ % (" AND ".join(where), column, direction)
        with self.database.connect() as conn:
            return conn.execute(sql, args).fetchall()

    def attachable_orders(self, product_id=None, variant_id=None):
        with self.database.connect() as conn:
            return conn.execute("""SELECT o.*,COALESCE(c.name,'No customer') customer_name,
                (SELECT COUNT(*) FROM print_jobs j
                 WHERE j.order_id=o.id AND (? IS NULL OR j.product_id=?)
                   AND (? IS NULL OR j.variant_id=?)
                   AND j.status IN ('queued','scheduled')) matching_waiting_jobs
                FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
                WHERE o.status IN ('confirmed','in_production','production')
                ORDER BY CASE o.status WHEN 'in_production' THEN 0 WHEN 'confirmed' THEN 1 ELSE 2 END,
                         o.created_at DESC""",(product_id,product_id,variant_id,variant_id)).fetchall()

    def find_attachable_job(self, order_id, product_id, variant_id=None):
        if not order_id or not product_id:return None
        with self.database.connect() as conn:
            return conn.execute("""SELECT * FROM print_jobs
                WHERE order_id=? AND product_id=? AND (? IS NULL OR variant_id=?) AND status IN ('queued','scheduled')
                ORDER BY created_at LIMIT 1""",(order_id,product_id,variant_id,variant_id)).fetchone()

    def job_print_readiness(self,job_id,design_vault):
        job=self.get(job_id)
        if not job["product_id"]:
            return {"ready":False,"state":"attention","reason":"No Catalog product attached","gcode":None}
        status=design_vault.product_print_status(job["product_id"])
        if not status.get("ready"):
            return {"ready":False,"state":"attention","reason":"Product needs an STL or saved G-code","gcode":None}
        if job["spool_id"]:
            with self.database.connect() as conn:
                spool=conn.execute("SELECT * FROM filament_spools WHERE id=?",(job["spool_id"],)).fetchone()
        else:spool=None
        if job["printer_id"]:
            with self.database.connect() as conn:
                printer=conn.execute("SELECT * FROM printers WHERE id=?",(job["printer_id"],)).fetchone()
        else:printer=None
        if status.get("has_gcode"):
            match=design_vault.best_gcode_for(
                job["product_id"],
                spool["material"] if spool else None,
                printer["name"] if printer else None)
            if match:
                return {"ready":True,"state":"gcode","reason":"Matching saved G-code ready",
                        "gcode":str(match["stored_path"])}
            if status.get("has_stl"):
                return {"ready":True,"state":"stl","reason":"STL ready; saved G-code does not match assigned material","gcode":None}
            return {"ready":False,"state":"attention","reason":"Saved G-code does not match assigned material","gcode":None}
        return {"ready":True,"state":"stl","reason":"STL ready to slice","gcode":None}

    def printers(self):
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT * FROM printers ORDER BY CASE status WHEN 'printing' THEN 0 WHEN 'idle' THEN 1 ELSE 2 END,name"
            ).fetchall()

    def spools(self):
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT * FROM filament_spools WHERE active=1 ORDER BY material,color,brand"
            ).fetchall()

    def create_jobs_from_order(self, order_id):
        created = []
        with self.database.connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
            if not order:
                raise KeyError("Order not found.")
            order_status = str(order["status"] or "").strip().lower()
            if order_status not in {"confirmed", "in_production", "production"}:
                raise ValueError("Order must be confirmed before production jobs can be created.")
            if not order["quote_id"]:
                raise ValueError("This order has no quote items.")
            items = conn.execute(
                """SELECT qi.*,p.name product_name FROM quote_items qi
                   LEFT JOIN products p ON p.id=qi.product_id
                   WHERE qi.quote_id=?""", (order["quote_id"],)
            ).fetchall()
            for item in items:
                existing = conn.execute(
                    "SELECT COUNT(*) FROM print_jobs WHERE order_id=? AND product_id IS ? AND variant_id IS ?",
                    (order_id, item["product_id"], item["variant_id"]),
                ).fetchone()[0]
                needed = max(0, int(item["quantity"] or 1) - int(existing))
                for _ in range(needed):
                    job_id = str(uuid.uuid4())
                    conn.execute(
                        """INSERT INTO print_jobs
                        (id,order_id,product_id,variant_id,status,estimated_minutes,estimated_filament_g)
                        VALUES (?,?,?,?,?,?,?)""",
                        (job_id, order_id, item["product_id"], item["variant_id"], "queued",
                         item["estimated_minutes"] or 0, item["estimated_filament_g"] or 0),
                    )
                    created.append(job_id)
            if created and order_status == "confirmed":
                conn.execute("UPDATE orders SET status='in_production' WHERE id=?", (order_id,))
            conn.commit()
        return created

    def create_jobs_for_all_new_orders(self):
        total = 0
        with self.database.connect() as conn:
            orders = conn.execute(
                "SELECT id FROM orders WHERE status IN ('confirmed','in_production','production') ORDER BY created_at"
            ).fetchall()
        for order in orders:
            total += len(self.create_jobs_from_order(order["id"]))
        return total

    def assign(self, job_id, printer_id=None, spool_id=None):
        with self.database.connect() as conn:
            job = conn.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not job:
                raise KeyError("Print job not found.")
            if printer_id:
                printer = conn.execute("SELECT * FROM printers WHERE id=?", (printer_id,)).fetchone()
                if not printer:
                    raise KeyError("Printer not found.")
                if str(printer["status"] or "").lower() in ("offline", "error"):
                    raise ValueError("Printer is offline or in error state.")
                occupied = conn.execute(
                    """SELECT 1 FROM print_jobs
                       WHERE printer_id=? AND id<>?
                         AND status IN ('queued','scheduled','printing','paused')
                       LIMIT 1""",
                    (printer_id, job_id),
                ).fetchone()
                if occupied:
                    raise ValueError("Printer already has an assigned active production job.")
            if spool_id:
                spool = conn.execute(
                    "SELECT * FROM filament_spools WHERE id=? AND active=1",
                    (spool_id,),
                ).fetchone()
                if not spool:
                    raise KeyError("Filament spool not found or inactive.")
                needed = float(job["estimated_filament_g"] or 0)
                requested_material = conn.execute(
                    """SELECT qi.material
                       FROM quote_items qi JOIN orders o ON o.quote_id=qi.quote_id
                       WHERE o.id=? AND qi.product_id=?
                         AND (qi.variant_id=? OR (qi.variant_id IS NULL AND ? IS NULL))
                       ORDER BY qi.rowid LIMIT 1""",
                    (job["order_id"], job["product_id"], job["variant_id"], job["variant_id"]),
                ).fetchone() if job["order_id"] and job["product_id"] else None
                if requested_material and str(requested_material["material"] or "").strip():
                    if str(spool["material"] or "").strip().lower() != str(requested_material["material"]).strip().lower():
                        raise ValueError("Filament spool material does not match the order requirement.")
                committed = conn.execute(
                    """SELECT COALESCE(SUM(COALESCE(estimated_filament_g,0)),0)
                       FROM print_jobs
                       WHERE spool_id=? AND id<>?
                         AND status IN ('queued','scheduled','printing','paused')""",
                    (spool_id, job_id),
                ).fetchone()[0]
                if float(spool["remaining_g"] or 0) - float(committed or 0) < needed:
                    raise ValueError("Filament spool does not have enough uncommitted material.")
            conn.execute(
                """UPDATE print_jobs SET printer_id=?,spool_id=?,
                   status=CASE WHEN status='queued' AND ? IS NOT NULL THEN 'scheduled' ELSE status END
                   WHERE id=?""",
                (printer_id, spool_id, printer_id, job_id),
            )
            conn.commit()

    def queue_additional_copies(self, job_id, copies):
        """Queue additional physical copies without starting them automatically."""
        copies = int(copies or 0)
        if copies <= 0:
            return []
        source = self.get(job_id)
        created = []
        with self.database.connect() as conn:
            for _ in range(copies):
                new_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO print_jobs
                    (id,order_id,product_id,variant_id,printer_id,spool_id,status,estimated_minutes,estimated_filament_g,quantity)
                    VALUES(?,?,?,?,?,?,?,?,?,1)""",
                    (new_id, source["order_id"], source["product_id"], source["variant_id"], None, None, "queued",
                     source["estimated_minutes"] or 0, source["estimated_filament_g"] or 0),
                )
                created.append(new_id)
            conn.commit()
        return created

    def set_status(self, job_id, status, actual_minutes=None, actual_filament_g=None):
        status=str(status or "").strip().lower()
        if status not in self.VALID_JOB_STATUSES:
            raise ValueError("Invalid print job status.")
        now = datetime.now().isoformat(timespec="seconds")
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM print_jobs WHERE id=?", (job_id,)).fetchone()
            if not row:
                raise KeyError("Print job not found.")
            current=str(row["status"] or "queued").strip().lower()
            if status not in self.JOB_STATUS_TRANSITIONS.get(current,{current}):
                raise ValueError("Invalid print job status transition.")
            values = {"status": status}
            if status == "printing" and not row["started_at"]:
                values["started_at"] = now
            if status in ("completed", "failed", "cancelled"):
                values["completed_at"] = now
                if row["started_at"] and not row["actual_minutes"]:
                    try:
                        start = datetime.fromisoformat(row["started_at"])
                        values["actual_minutes"] = max(1, int((datetime.now() - start).total_seconds() / 60))
                    except Exception:
                        pass
                values["success"] = 1 if status == "completed" else 0
            setters = ",".join("%s=?" % key for key in values)
            args = list(values.values()) + [job_id]
            conn.execute("UPDATE print_jobs SET %s WHERE id=?" % setters, args)
            if row["printer_id"]:
                printer_state = "printing" if status == "printing" else "idle"
                conn.execute("UPDATE printers SET status=? WHERE id=?", (printer_state, row["printer_id"]))
            if status == "completed" and row["order_id"]:
                remaining = conn.execute(
                    "SELECT COUNT(*) FROM print_jobs WHERE order_id=? AND status NOT IN ('completed','cancelled')",
                    (row["order_id"],),
                ).fetchone()[0]
                if remaining == 0:
                    conn.execute("UPDATE orders SET status='qc' WHERE id=?", (row["order_id"],))
            conn.commit()
        if status in ("completed","failed"):
            try:
                from fabos_core.services.manufacturing import ManufacturingService
                m=ManufacturingService(self.database)
                if status=="completed":
                    # Completion is the authoritative point at which actual/estimated
                    # material consumption is recorded. The manufacturing service is
                    # idempotent, so repeated reconciliation cannot double-deduct a spool.
                    m.complete_with_inventory(job_id, actual_minutes, actual_filament_g)
                    if row["order_id"]:
                        m.ensure_qc(row["order_id"],job_id)
                else:
                    # Failed prints consume material too. Record waste independently
                    # so a learning failure cannot silently skip inventory accounting.
                    from fabos_core.services.inventory_profit import InventoryProfitService
                    InventoryProfitService(self.database).record_failed_waste(job_id)
                    m.learn(job_id)
            except Exception:
                pass

    def get(self, job_id):
        rows = self.list_jobs()
        for row in rows:
            if row["id"] == job_id:
                return row
        raise KeyError("Print job not found.")

    def ensure_default_vyper(self):
        with self.database.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM printers").fetchone()[0]
            if not count:
                printer_id = str(uuid.uuid4())
                conn.execute(
                    """INSERT INTO printers
                    (id,name,model,status,build_x_mm,build_y_mm,build_z_mm,total_hours)
                    VALUES (?,?,?,?,?,?,?,0)""",
                    (printer_id, "Anycubic Vyper", "Anycubic Vyper", "idle", 245, 245, 260),
                )
                conn.commit()
                return printer_id
        return None
