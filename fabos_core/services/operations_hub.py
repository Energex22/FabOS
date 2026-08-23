import json,uuid
from datetime import datetime

class OperationsHubService:
    def __init__(self,app):
        self.app=app
        self.db=app.database

    def log(self,event_type,title,detail="",page="",entity_id="",undo_type=None,undo_payload=None):
        with self.db.connect() as c:
            c.execute("""INSERT INTO activity_journal(
              id,event_type,title,detail,page,entity_id,undo_type,undo_payload_json)
              VALUES(?,?,?,?,?,?,?,?)""",
              (str(uuid.uuid4()),event_type,title,detail,page,entity_id,undo_type,
               json.dumps(undo_payload) if undo_payload is not None else None))
            c.commit()

    def recent_activity(self,limit=20):
        with self.db.connect() as c:
            return c.execute("""SELECT * FROM activity_journal
              ORDER BY created_at DESC LIMIT ?""",(int(limit),)).fetchall()

    def _upsert_notification(self,key,severity,title,body,page,entity_id=""):
        with self.db.connect() as c:
            c.execute("""INSERT INTO notifications(
              id,dedupe_key,severity,title,body,page,entity_id,is_read)
              VALUES(?,?,?,?,?,?,?,0)
              ON CONFLICT(dedupe_key) DO UPDATE SET
                severity=excluded.severity,title=excluded.title,body=excluded.body,
                page=excluded.page,entity_id=excluded.entity_id,updated_at=CURRENT_TIMESTAMP""",
              (str(uuid.uuid4()),key,severity,title,body,page,entity_id))
            c.commit()

    def dismiss_stale_notifications(self,active_keys):
        active=set(active_keys)
        with self.db.connect() as c:
            rows=c.execute("SELECT dedupe_key FROM notifications").fetchall()
            for row in rows:
                key=str(row["dedupe_key"] or "")
                if key.startswith("event:"):
                    continue
                if key not in active:
                    c.execute("DELETE FROM notifications WHERE dedupe_key=?",(key,))
            c.commit()

    def action_items(self):
        items=[]
        app=self.app
        try:
            if app.recovery.previous_unclean:
                items.append({"severity":"medium","title":"Previous FabOS session ended unexpectedly",
                              "detail":"Crash recovery ran at startup. Review active printers/jobs, then restart FabOS normally to clear this warning.",
                              "page":"Backup & Health","id":"","key":"recovery:unclean"})
        except Exception:
            pass
        low=float(app.shop_settings.get("filament_low_threshold_g","250") or 250)
        today=datetime.now().date().isoformat()
        with self.db.connect() as c:
            # Printers needing attention
            printers=c.execute("""SELECT * FROM printers ORDER BY name""").fetchall()
            for p in printers:
                state=str(p["status"] or "").lower()
                if state in ("offline","error") or str(p["octoprint_state_text"] or "").lower() in ("printer not responding","offline","error"):
                    items.append({"severity":"high","title":"Printer needs attention",
                                  "detail":"%s — %s"%(p["name"],p["octoprint_state_text"] or p["status"]),
                                  "page":"Printers","id":p["id"],"key":"printer:"+p["id"]})
                elif state=="printing":
                    left=float(p["print_time_left_seconds"] or 0)
                    detail="%s is printing"%p["name"]
                    if left>0:detail+=" • about %dh %02dm remaining"%(int(left)//3600,(int(left)%3600)//60)
                    items.append({"severity":"info","title":"Print in progress","detail":detail,
                                  "page":"Printers","id":p["id"],"key":"printing:"+p["id"]})

            # Production states
            jobs=c.execute("""SELECT j.*,COALESCE(p.name,'Custom Job') product_name,
                COALESCE(o.order_number,'Personal') order_number
                FROM print_jobs j LEFT JOIN products p ON p.id=j.product_id
                LEFT JOIN orders o ON o.id=j.order_id
                WHERE j.status IN ('queued','scheduled','failed') ORDER BY j.created_at""").fetchall()
            for j in jobs:
                if j["status"]=="failed":
                    items.append({"severity":"high","title":"Failed print",
                                  "detail":"%s • %s"%(j["product_name"],j["failure_reason"] or "Review required"),
                                  "page":"Production","id":j["id"],"key":"failed:"+j["id"]})
                    continue
                if not j["printer_id"] or not j["spool_id"]:
                    items.append({"severity":"medium","title":"Production job needs assignment",
                                  "detail":"%s • %s needs a printer and filament spool"%(j["order_number"],j["product_name"]),
                                  "page":"Production","id":j["id"],"key":"assign:"+j["id"]})
                    continue
                try:ready=app.production.job_print_readiness(j["id"],app.design_vault)
                except Exception:ready={"ready":False,"reason":"Check print file"}
                if ready.get("ready"):
                    items.append({"severity":"info","title":"Production ready to print",
                                  "detail":"%s • %s • %s"%(j["order_number"],j["product_name"],ready.get("reason","Ready")),
                                  "page":"Production","id":j["id"],"key":"readyjob:"+j["id"]})
                else:
                    items.append({"severity":"medium","title":"Production needs print file",
                                  "detail":"%s • %s • %s"%(j["order_number"],j["product_name"],ready.get("reason","Needs attention")),
                                  "page":"Production","id":j["id"],"key":"jobfile:"+j["id"]})

            # Quotes waiting on approval / expiring
            quotes=c.execute("""SELECT q.id,q.quote_number,q.status,q.expires_at,COALESCE(cu.name,'No customer') customer_name
                FROM quotes q LEFT JOIN customers cu ON cu.id=q.customer_id
                WHERE q.status IN ('draft','sent') ORDER BY q.expires_at,q.created_at""").fetchall()
            for q in quotes:
                if q["status"]=='sent':
                    expired=bool(q["expires_at"] and str(q["expires_at"])<today)
                    items.append({"severity":"high" if expired else "medium",
                                  "title":"Quote expired" if expired else "Quote awaiting approval",
                                  "detail":"%s • %s"%(q["quote_number"],q["customer_name"]),
                                  "page":"Quotes","id":q["id"],"key":"quote:"+q["id"]})

            # Active overdue orders
            overdue_orders=c.execute("""SELECT o.id,o.order_number,o.due_at,COALESCE(cu.name,'No customer') customer_name
                FROM orders o LEFT JOIN customers cu ON cu.id=o.customer_id
                WHERE o.status NOT IN ('completed','cancelled','shipped') AND o.due_at IS NOT NULL AND o.due_at<?
                ORDER BY o.due_at""",(today,)).fetchall()
            for o in overdue_orders:
                items.append({"severity":"high","title":"Order overdue",
                              "detail":"%s • %s • due %s"%(o["order_number"],o["customer_name"],o["due_at"]),
                              "page":"Orders","id":o["id"],"key":"overdue:"+o["id"]})

            # QC
            qc=c.execute("""SELECT q.id,q.order_id,q.print_job_id,o.order_number
                FROM qc_inspections q LEFT JOIN orders o ON o.id=q.order_id
                WHERE q.status='pending' ORDER BY q.created_at""").fetchall()
            for q in qc:
                items.append({"severity":"medium","title":"QC waiting",
                              "detail":"Order %s has a completed print waiting for inspection"%(q["order_number"] or "—"),
                              "page":"QC","id":q["id"],"key":"qc:"+q["id"]})

            # Ready orders / shipping
            orders=c.execute("""SELECT o.id,o.order_number,o.status,COALESCE(cu.name,'No customer') customer_name,
                COALESCE(f.status,'pending') fulfillment_status,COALESCE(f.method,'') fulfillment_method
                FROM orders o LEFT JOIN customers cu ON cu.id=o.customer_id
                LEFT JOIN fulfillments f ON f.order_id=o.id
                WHERE o.status='ready' ORDER BY o.due_at,o.created_at""").fetchall()
            for o in orders:
                fs=str(o["fulfillment_status"] or "pending")
                title=("Packed — ready to ship" if fs=="packed" else
                       "Ready for customer pickup" if fs=="ready_for_pickup" else "Ready to pack / ship")
                items.append({"severity":"medium","title":title,
                              "detail":"%s • %s"%(o["order_number"],o["customer_name"]),
                              "page":"Orders","id":o["id"],"key":"ship:"+o["id"]})

            # Unpaid invoices
            invoices=c.execute("""SELECT i.id,i.invoice_number,i.total_cents,i.paid_cents,i.due_at
                FROM invoices i WHERE i.status IN ('open','partial')
                ORDER BY i.due_at,i.created_at""").fetchall()
            for inv in invoices:
                balance=max(0,int(inv["total_cents"] or 0)-int(inv["paid_cents"] or 0))
                overdue=bool(inv["due_at"] and str(inv["due_at"])<today)
                items.append({"severity":"high" if overdue else "medium",
                              "title":"Overdue invoice" if overdue else "Unpaid invoice",
                              "detail":"%s • $%.2f balance"%(inv["invoice_number"],balance/100.0),
                              "page":"Invoices","id":inv["id"],"key":"invoice:"+inv["id"]})

            # Low filament
            spools=c.execute("""SELECT * FROM filament_spools WHERE active=1 AND remaining_g<?
                ORDER BY remaining_g""",(low,)).fetchall()
            for s in spools:
                items.append({"severity":"medium","title":"Low filament",
                              "detail":"%s %s • %.0fg remaining"%(s["material"],s["color"] or "",s["remaining_g"]),
                              "page":"Filament","id":s["id"],"key":"spool:"+s["id"]})

        try:
            for s in app.supplies.low():
                items.append({"severity":"medium","title":"Low packaging / supply",
                              "detail":"%s • %g %s remaining"%(s["name"],s["quantity"],s["unit"]),
                              "page":"Filament","id":s["id"],"key":"supply:"+s["id"]})
        except Exception:
            pass

        # Catalog readiness uses service so paths are verified.
        try:
            products=app.products.list()
            status=app.design_vault.product_print_status_map([p["id"] for p in products])
            for p in products:
                if not status.get(p["id"],{}).get("ready"):
                    items.append({"severity":"medium","title":"Catalog needs print file",
                                  "detail":p["name"]+" needs an STL or G-code",
                                  "page":"Products","id":p["id"],"key":"catalog:"+p["id"]})
        except Exception:
            pass
        return items

    def reconcile_workflows(self):
        """Repair/advance deterministic workflow states without requiring manual clicks."""
        today=datetime.now().date().isoformat()
        with self.db.connect() as c:
            # Expired sent quotes leave Active Quotes automatically and create a
            # one-time notification so the transition is still visible.
            expired=c.execute("""SELECT q.id,q.quote_number,COALESCE(cu.name,'No customer') customer_name
              FROM quotes q LEFT JOIN customers cu ON cu.id=q.customer_id
              WHERE q.status='sent' AND q.expires_at IS NOT NULL AND q.expires_at<?""",(today,)).fetchall()
            c.execute("""UPDATE quotes SET status='expired'
              WHERE status='sent' AND expires_at IS NOT NULL AND expires_at<?""",(today,))
            for q in expired:
                c.execute("""INSERT OR IGNORE INTO notifications(
                  id,dedupe_key,severity,title,body,page,entity_id,is_read) VALUES(?,?,?,?,?,?,?,0)""",
                  (str(uuid.uuid4()),'event:quoteexpired:'+q['id'],'medium','Quote expired',
                   '%s • %s'%(q['quote_number'],q['customer_name']),'Quotes',q['id']))

            # If every production job on an active order is complete/cancelled, move to QC.
            c.execute("""UPDATE orders SET status='qc' WHERE status='production'
              AND EXISTS(SELECT 1 FROM print_jobs j WHERE j.order_id=orders.id)
              AND NOT EXISTS(SELECT 1 FROM print_jobs j WHERE j.order_id=orders.id
                             AND j.status NOT IN ('completed','cancelled'))""")

            # If all QC records are passed, order is ready for fulfillment.
            c.execute("""UPDATE orders SET status='ready' WHERE status='qc'
              AND EXISTS(SELECT 1 FROM qc_inspections q WHERE q.order_id=orders.id)
              AND NOT EXISTS(SELECT 1 FROM qc_inspections q WHERE q.order_id=orders.id AND q.status<>'passed')""")

            # Delivered/picked-up + fully-paid becomes Completed, even if the app was
            # closed when one of those two conditions changed.
            c.execute("""UPDATE orders SET status='completed'
              WHERE status IN ('ready','shipped')
              AND EXISTS(SELECT 1 FROM fulfillments f WHERE f.order_id=orders.id
                         AND f.status IN ('delivered','picked_up'))
              AND EXISTS(SELECT 1 FROM invoices i WHERE i.order_id=orders.id AND i.status<>'void'
                         AND i.paid_cents>=i.total_cents)""")
            c.commit()

    def refresh_notifications(self):
        self.reconcile_workflows()
        items=self.action_items()
        active=[]
        for item in items:
            if item["severity"]=="info":continue
            active.append(item["key"])
            self._upsert_notification(item["key"],item["severity"],item["title"],item["detail"],item["page"],item.get("id",""))
        self.dismiss_stale_notifications(active)
        return items

    def notifications(self,unread_only=True,limit=50):
        self.refresh_notifications()
        with self.db.connect() as c:
            where="WHERE is_read=0" if unread_only else ""
            return c.execute("""SELECT * FROM notifications %s
              ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                       updated_at DESC LIMIT ?"""%where,(int(limit),)).fetchall()

    def unread_count(self):
        self.refresh_notifications()
        with self.db.connect() as c:
            return c.execute("SELECT COUNT(*) FROM notifications WHERE is_read=0").fetchone()[0]

    def mark_notification_read(self,nid):
        with self.db.connect() as c:
            c.execute("UPDATE notifications SET is_read=1 WHERE id=?",(nid,));c.commit()

    def mark_all_notifications_read(self):
        with self.db.connect() as c:
            c.execute("UPDATE notifications SET is_read=1");c.commit()

    def print_next(self):
        """Pick the best immediately runnable production job."""
        with self.db.connect() as c:
            jobs=c.execute("""SELECT j.*,o.due_at,o.created_at order_created,
                COALESCE(o.order_number,'Personal') order_number
                FROM print_jobs j LEFT JOIN orders o ON o.id=j.order_id
                WHERE j.status IN ('queued','scheduled')
                ORDER BY CASE WHEN o.due_at IS NULL THEN 1 ELSE 0 END,o.due_at,o.created_at,j.created_at""").fetchall()
        best=None
        for j in jobs:
            if not j["printer_id"] or not j["spool_id"] or not j["product_id"]:continue
            with self.db.connect() as c:
                printer=c.execute("SELECT * FROM printers WHERE id=?",(j["printer_id"],)).fetchone()
                spool=c.execute("SELECT * FROM filament_spools WHERE id=?",(j["spool_id"],)).fetchone()
            if not printer or str(printer["status"] or "").lower() not in ("idle","online","operational"):continue
            if not spool:continue
            needed=float(j["estimated_filament_g"] or 0)
            if needed>0 and float(spool["remaining_g"] or 0)<needed:continue
            readiness=self.app.production.job_print_readiness(j["id"],self.app.design_vault)
            if not readiness.get("ready"):continue
            best={"job":j,"printer":printer,"spool":spool,"readiness":readiness}
            break
        return best

    def filament_check(self,job_id):
        with self.db.connect() as c:
            j=c.execute("""SELECT j.*,s.material,s.color,s.remaining_g FROM print_jobs j
                LEFT JOIN filament_spools s ON s.id=j.spool_id WHERE j.id=?""",(job_id,)).fetchone()
        if not j:return {"ok":False,"message":"Print job not found."}
        need=float(j["estimated_filament_g"] or 0)
        have=float(j["remaining_g"] or 0)
        return {"ok":have>=need,"required_g":need,"remaining_g":have,
                "after_g":have-need,"material":j["material"],"color":j["color"]}

    def system_ready(self):
        checks=list(self.app.reliability.health_safe())
        try:
            items=self.action_items()
            attention=sum(1 for x in items if x["severity"] in ("high","medium"))
            checks.append({"name":"Action Center","status":"pass" if attention==0 else "warn",
                           "detail":"Ready" if attention==0 else "%d item%s need attention"%(attention,"" if attention==1 else "s")})
        except Exception as exc:
            checks.append({"name":"Action Center","status":"warn","detail":str(exc)})
        return checks
