"""Administrator-only API routes for FabOS administration."""


def register_admin_routes(app, get_application, administrator_user):
    from typing import Optional
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel, Field

    class AccountUpdate(BaseModel):
        email: Optional[str] = Field(default=None, max_length=320)
        account_type: Optional[str] = Field(default=None, max_length=30)
        active: Optional[bool] = None

    class PasswordReset(BaseModel):
        password: str = Field(min_length=8, max_length=1024)

    class PermissionUpdate(BaseModel):
        allowed: bool

    class SettingUpdate(BaseModel):
        key: str = Field(min_length=1, max_length=100)
        value: str = Field(default="", max_length=4000)

    class PricingEstimate(BaseModel):
        estimated_minutes: float = Field(default=0, ge=0)
        estimated_filament_g: float = Field(default=0, ge=0)
        quantity: int = Field(default=1, ge=1, le=1000)
        rush: bool = False
        setup_minutes: float = Field(default=0, ge=0)
        post_process_minutes: float = Field(default=0, ge=0)
        qc_minutes: float = Field(default=0, ge=0)
        overhead_percent: Optional[float] = Field(default=None, ge=0, le=100)

    def operations_user(user=Depends(app.state.current_user), application=Depends(get_application)):
        account_type = str(user["account_type"] or "").lower()
        if account_type not in ("employee", "administrator"):
            raise HTTPException(status_code=403, detail="Team account required")
        if not application.permissions.has_permission(account_type, "production.read", user_id=user["id"]):
            raise HTTPException(status_code=403, detail="Operations access denied")
        return user

    @app.get("/api/v1/admin/operations/dashboard")
    def operations_dashboard(user=Depends(operations_user), application=Depends(get_application)):
        from datetime import datetime, timedelta
        now = datetime.now()
        today = now.date().isoformat()
        month_start = (now.date() - timedelta(days=29)).isoformat()
        with application.database.connect() as conn:
            def scalar(sql, args=()):
                return conn.execute(sql, args).fetchone()[0] or 0

            orders_today = int(scalar("SELECT COUNT(*) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')", (today,)))
            sales_today = int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')", (today,)))
            sales_30d = int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)>=date(?) AND status NOT IN ('cancelled')", (month_start,)))
            active_orders = int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped')"))
            active_jobs = int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('queued','scheduled','printing','paused')"))
            printing_jobs = int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('printing','paused')"))
            failed_jobs = int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status='failed'"))
            printer_total = int(scalar("SELECT COUNT(*) FROM printers"))
            printer_online = int(scalar("SELECT COUNT(*) FROM printers WHERE lower(COALESCE(status,'')) NOT IN ('offline','error')"))
            low_filament_threshold = float(application.shop_settings.get("filament_low_threshold_g", "250") or 250)
            low_filament = int(scalar("SELECT COUNT(*) FROM filament_spools WHERE active=1 AND remaining_g<?", (low_filament_threshold,)))
            low_supplies = int(scalar("SELECT COUNT(*) FROM supply_items WHERE active=1 AND quantity<=low_threshold"))
            open_quotes = int(scalar("SELECT COUNT(*) FROM quotes WHERE status IN ('draft','sent')"))
            unpaid = int(scalar("SELECT COUNT(*) FROM invoices WHERE status IN ('open','partial')"))
            overdue = int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped') AND due_at IS NOT NULL AND due_at<?", (today,)))
            pending_qc = int(scalar("SELECT COUNT(*) FROM qc_inspections WHERE status='pending'"))

            recent_orders = [dict(row) for row in conn.execute("""
                SELECT o.id,o.order_number,o.status,o.total_cents,o.due_at,o.created_at,COALESCE(c.name,'No customer') customer_name
                FROM orders o LEFT JOIN customers c ON c.id=o.customer_id
                ORDER BY o.created_at DESC LIMIT 8""").fetchall()]
            jobs = [dict(row) for row in conn.execute("""
                SELECT j.id,j.status,j.estimated_minutes,j.print_time_left_seconds,COALESCE(p.name,'Custom Job') product_name,
                       COALESCE(pr.name,'Unassigned') printer_name,COALESCE(o.order_number,'Personal') order_number,
                       COALESCE(fs.material || ' ' || COALESCE(fs.color,''),'No spool') spool_name
                FROM print_jobs j LEFT JOIN products p ON p.id=j.product_id LEFT JOIN printers pr ON pr.id=j.printer_id
                LEFT JOIN orders o ON o.id=j.order_id LEFT JOIN filament_spools fs ON fs.id=j.spool_id
                WHERE j.status IN ('queued','scheduled','printing','paused','failed')
                ORDER BY CASE j.status WHEN 'failed' THEN 0 WHEN 'printing' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END,j.created_at LIMIT 12""").fetchall()]
            printers = [dict(row) for row in conn.execute("""
                SELECT id,name,model,status,connection_mode,simulation_progress,nozzle_temp,bed_temp,
                       print_time_seconds,print_time_left_seconds,octoprint_state_text,octoprint_current_file,last_seen_at,total_hours
                FROM printers ORDER BY name""").fetchall()]
            low_spools = [dict(row) for row in conn.execute("""
                SELECT id,material,brand,color,remaining_g,initial_g,cost_cents,location
                FROM filament_spools WHERE active=1 AND remaining_g<? ORDER BY remaining_g LIMIT 10""",(low_filament_threshold,)).fetchall()]
            maintenance = [dict(row) for row in conn.execute("""
                SELECT p.id,p.name,p.total_hours,COALESCE(MAX(m.printer_hours),0) last_service_hours,
                       p.total_hours-COALESCE(MAX(m.printer_hours),0) hours_since_service
                FROM printers p LEFT JOIN maintenance_records m ON m.printer_id=p.id
                GROUP BY p.id ORDER BY hours_since_service DESC""").fetchall()]

        action_items=[]
        try:
            action_items=[dict(item) for item in application.operations.action_items()[:20]]
        except Exception:
            pass
        return {
            "generated_at": now.isoformat(timespec="seconds"),
            "viewer": {"id": user["id"], "account_type": user["account_type"], "role": user["role"]},
            "business": {"orders_today": orders_today, "sales_today_cents": sales_today, "sales_30d_cents": sales_30d, "active_orders": active_orders, "open_quotes": open_quotes, "unpaid_invoices": unpaid, "overdue_orders": overdue, "pending_qc": pending_qc},
            "production": {"active_jobs": active_jobs, "printing_jobs": printing_jobs, "failed_jobs": failed_jobs, "jobs": jobs, "automation": {"enabled": str(application.shop_settings.get("production_automation_enabled","true")).lower() in ("1","true","yes","on"), "auto_assign": str(application.shop_settings.get("production_auto_assign","true")).lower() in ("1","true","yes","on"), "auto_start": str(application.shop_settings.get("production_auto_start","false")).lower() in ("1","true","yes","on"), "last_run": application.production_automation.last_run}},
            "printers": {"total": printer_total, "online": printer_online, "items": printers},
            "inventory": {"low_filament": low_filament, "low_supplies": low_supplies, "filament_threshold_g": low_filament_threshold, "spools": low_spools},
            "maintenance": {"items": maintenance},
            "recent_orders": recent_orders,
            "action_items": action_items,
        }

    @app.post("/api/v1/admin/operations/automation/tick")
    def run_operations_automation(user=Depends(operations_user), application=Depends(get_application)):
        return application.production_automation.tick()

    @app.get("/api/v1/admin/users")
    def list_admin_users(user=Depends(administrator_user), application=Depends(get_application)):
        rows = application.accounts.list_users()
        users = []
        for row in rows:
            item = {key: row[key] for key in ("id", "username", "email", "account_type", "role", "active", "created_at", "updated_at", "last_login_at") if key in row.keys()}
            item["permissions"] = sorted(application.permissions.permissions_for_user(row["id"], row["account_type"]))
            users.append(item)
        return {"users": users}

    @app.get("/api/v1/admin/users/{user_id}")
    def get_admin_user(user_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        row = application.accounts.get_user(user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        summary = application.accounts.account_summary(user_id)
        return {
            "user": {key: row[key] for key in ("id", "username", "email", "account_type", "role", "active", "created_at", "updated_at", "last_login_at") if key in row.keys()},
            "customer": summary.get("customer"),
            "employee": summary.get("employee"),
            "permissions": sorted(application.permissions.permissions_for_user(user_id, row["account_type"])),
        }

    @app.patch("/api/v1/admin/users/{user_id}")
    def update_admin_user(user_id: str, payload: AccountUpdate, user=Depends(administrator_user), application=Depends(get_application)):
        row = application.accounts.get_user(user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        values = payload.dict(exclude_unset=True)
        target_is_owner = str(row["role"] or "").lower() == "owner" if "role" in row.keys() else False
        actor_is_owner = str(user["role"] or "").lower() == "owner" if "role" in user.keys() else False
        if target_is_owner and not actor_is_owner:
            raise HTTPException(status_code=403, detail="Only the owner can modify the owner account")
        if user_id == user["id"] and (values.get("active") is False or values.get("account_type") not in (None, "administrator")):
            raise HTTPException(status_code=409, detail="You cannot disable or demote your own administrator account")
        if row["account_type"] == "administrator" and (values.get("active") is False or values.get("account_type") not in (None, "administrator")):
            administrators = application.accounts.list_users(account_type="administrator", active_only=True)
            if len(administrators) <= 1:
                raise HTTPException(status_code=409, detail="At least one active administrator account must remain")
        updated = application.accounts.update_account(user_id, **values)
        return {"user": {key: updated[key] for key in ("id", "username", "email", "account_type", "active", "created_at", "updated_at", "last_login_at") if key in updated.keys()}}

    @app.post("/api/v1/admin/users/{user_id}/password")
    def reset_admin_password(user_id: str, payload: PasswordReset, user=Depends(administrator_user), application=Depends(get_application)):
        target = application.accounts.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if str(target["role"] or "").lower() == "owner" and str(user["role"] or "").lower() != "owner":
            raise HTTPException(status_code=403, detail="Only the owner can change the owner password")
        application.auth.set_password(user_id, payload.password)
        revoked = application.auth.revoke_user_sessions(user_id)
        return {"updated": True, "sessions_revoked": revoked}

    @app.post("/api/v1/admin/users/{user_id}/revoke-sessions")
    def revoke_admin_sessions(user_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        if not application.accounts.get_user(user_id):
            raise HTTPException(status_code=404, detail="User not found")
        return {"sessions_revoked": application.auth.revoke_user_sessions(user_id)}

    @app.get("/api/v1/admin/permissions")
    def list_permissions(user=Depends(administrator_user), application=Depends(get_application)):
        return {
            "permissions": list(application.permissions.all_permissions()),
            "roles": {role: sorted(application.permissions.permissions_for_account_type(role)) for role in ("customer", "employee", "administrator")},
        }

    @app.get("/api/v1/admin/users/{user_id}/permissions")
    def get_user_permissions(user_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        row = application.accounts.get_user(user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        return {
            "user_id": user_id,
            "account_type": row["account_type"],
            "effective": sorted(application.permissions.permissions_for_user(user_id, row["account_type"])),
            "role_default": sorted(application.permissions.permissions_for_account_type(row["account_type"])),
        }

    @app.put("/api/v1/admin/users/{user_id}/permissions/{permission}")
    def set_user_permission(user_id: str, permission: str, payload: PermissionUpdate, user=Depends(administrator_user), application=Depends(get_application)):
        target = application.accounts.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if str(target["role"] or "").lower() == "owner" and str(user["role"] or "").lower() != "owner":
            raise HTTPException(status_code=403, detail="Only the owner can modify owner permissions")
        try:
            application.permissions.set_user_permission(user_id, permission, payload.allowed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated": True, "permission": permission, "allowed": payload.allowed}

    @app.delete("/api/v1/admin/users/{user_id}/permissions/{permission}")
    def clear_user_permission(user_id: str, permission: str, user=Depends(administrator_user), application=Depends(get_application)):
        target = application.accounts.get_user(user_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        if str(target["role"] or "").lower() == "owner" and str(user["role"] or "").lower() != "owner":
            raise HTTPException(status_code=403, detail="Only the owner can modify owner permissions")
        try:
            application.permissions.clear_user_permission(user_id, permission)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated": True, "permission": permission, "override": None}

    @app.get("/api/v1/admin/settings")
    def get_admin_settings(user=Depends(administrator_user), application=Depends(get_application)):
        return {"settings": application.shop_settings.snapshot(), "metadata": application.shop_settings.metadata()}

    @app.put("/api/v1/admin/settings")
    def update_admin_settings(payload: SettingUpdate, user=Depends(administrator_user), application=Depends(get_application)):
        protected_keys = {"console_lock_enabled", "console_idle_timeout_minutes", "console_local_only"}
        if payload.key in protected_keys and str(user["role"] or "").lower() != "owner":
            raise HTTPException(status_code=403, detail="Only the owner can change console security settings")
        try:
            application.shop_settings.set_validated(payload.key, payload.value)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"key": payload.key, "value": application.shop_settings.get(payload.key), "metadata": application.shop_settings.metadata().get(payload.key)}

    @app.post("/api/v1/admin/pricing/estimate")
    def estimate_admin_pricing(payload: PricingEstimate, user=Depends(administrator_user), application=Depends(get_application)):
        return application.pricing.estimate(
            estimated_minutes=payload.estimated_minutes,
            estimated_filament_g=payload.estimated_filament_g,
            quantity=payload.quantity,
            rush=payload.rush,
            setup_minutes=payload.setup_minutes,
            post_process_minutes=payload.post_process_minutes,
            qc_minutes=payload.qc_minutes,
            overhead_percent=payload.overhead_percent,
        )

    @app.get("/api/v1/admin/products/{product_id}/price-history")
    def get_product_price_history(product_id: str, limit: int = 100, user=Depends(administrator_user), application=Depends(get_application)):
        if not application.products.get(product_id):
            raise HTTPException(status_code=404, detail="Product not found")
        return {"history": [dict(row) for row in application.price_history.product(product_id, limit)]}

    @app.get("/api/v1/admin/variants/{variant_id}/price-history")
    def get_variant_price_history(variant_id: str, limit: int = 100, user=Depends(administrator_user), application=Depends(get_application)):
        with application.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM product_variants WHERE id=?", (variant_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Variant not found")
        return {"history": [dict(row) for row in application.price_history.variant(variant_id, limit)]}

    @app.get("/api/v1/admin/quotes/{quote_id}/price-snapshots")
    def get_quote_price_snapshots(quote_id: str, limit: int = 500, user=Depends(administrator_user), application=Depends(get_application)):
        with application.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM quotes WHERE id=?", (quote_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Quote not found")
        return {"snapshots": [dict(row) for row in application.price_history.quote_snapshots(quote_id, limit)]}

    @app.get("/api/v1/admin/orders/{order_id}/price-snapshots")
    def get_order_price_snapshots(order_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        with application.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone():
                raise HTTPException(status_code=404, detail="Order not found")
        return {"items": [dict(row) for row in application.price_history.order_items(order_id)]}


    @app.get("/api/v1/admin/ai/status")
    def ai_status(user=Depends(administrator_user), application=Depends(get_application)):
        return application.ai.status()

    @app.post("/api/v1/admin/ai/chat")
    def ai_chat(payload: dict, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            return {"response": application.ai.chat(payload.get("message", ""), payload.get("context"))}
        except (TypeError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/admin/ai/products/{product_id}/marketing")
    def ai_product_marketing(product_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            return {"product_id": product_id, "response": application.ai.marketing_assistant(product_id)}
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/admin/marketing/dashboard")
    def marketing_dashboard(user=Depends(administrator_user), application=Depends(get_application)):
        return application.marketing.dashboard()

    @app.get("/api/v1/admin/marketing/channels")
    def marketing_channels(user=Depends(administrator_user), application=Depends(get_application)):
        return {"channels": [dict(row) for row in application.marketing.channels()]}

    @app.put("/api/v1/admin/marketing/channels/{channel_id}")
    def update_marketing_channel(channel_id: str, payload: dict, user=Depends(administrator_user), application=Depends(get_application)):
        data = dict(payload or {})
        data["channel_id"] = channel_id
        try:
            row = application.marketing.save_channel(**data)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"channel": dict(row)}

    @app.post("/api/v1/admin/marketing/channels")
    def create_marketing_channel(payload: dict, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            row = application.marketing.save_channel(**dict(payload or {}))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"channel": dict(row)}

    @app.get("/api/v1/admin/marketing/campaigns")
    def marketing_campaigns(status: Optional[str] = None, user=Depends(administrator_user), application=Depends(get_application)):
        return {"campaigns": [dict(row) for row in application.marketing.campaigns(status)]}

    @app.post("/api/v1/admin/marketing/campaigns")
    def create_marketing_campaign(payload: dict, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            row = application.marketing.save_campaign(**dict(payload or {}))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"campaign": dict(row)}

    @app.get("/api/v1/admin/marketing/products/{product_id}/variants")
    def generate_marketing_variants(product_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            return {"product_id": product_id, "variants": application.marketing.generate_post_variants(product_id)}
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/v1/admin/marketing/posts")
    def marketing_posts(status: Optional[str] = None, limit: int = 100, user=Depends(administrator_user), application=Depends(get_application)):
        return {"posts": [dict(row) for row in application.marketing.posts(status, limit)]}

    @app.post("/api/v1/admin/marketing/posts")
    def create_marketing_post(payload: dict, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            row = application.marketing.create_post(**dict(payload or {}))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"post": dict(row)}

    @app.post("/api/v1/admin/marketing/posts/{post_id}/approve")
    def approve_marketing_post(post_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        post = application.marketing.post(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        if not post[1]:
            raise HTTPException(status_code=409, detail="Post has no channels")
        with application.database.connect() as conn:
            conn.execute("UPDATE marketing_posts SET status='scheduled',updated_at=CURRENT_TIMESTAMP WHERE id=?", (post_id,))
            conn.execute("UPDATE marketing_post_channels SET status='scheduled' WHERE post_id=? AND status='draft'", (post_id,))
            conn.commit()
        return {"approved": True, "post_id": post_id}

    @app.post("/api/v1/admin/marketing/posts/queue-due")
    def queue_due_marketing_posts(user=Depends(administrator_user), application=Depends(get_application)):
        return {"queued": application.marketing.queue_due_posts()}

    @app.get("/api/v1/admin/marketing/posts/{post_id}")
    def get_marketing_post(post_id: str, user=Depends(administrator_user), application=Depends(get_application)):
        post = application.marketing.post(post_id)
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        row, channels = post
        return {"post": dict(row), "channels": [dict(channel) for channel in channels]}

    @app.get("/api/v1/admin/marketing/sales")
    def marketing_sales(days: int = 30, user=Depends(administrator_user), application=Depends(get_application)):
        return {"days": max(1, min(days, 3650)), "channels": application.marketing.sales_summary(max(1, min(days, 3650)))}


    @app.get("/api/v1/admin/marketing/sales/external")
    def marketing_external_sales(channel_id: Optional[str] = None, limit: int = 100,
                                  user=Depends(administrator_user), application=Depends(get_application)):
        return {"sales": [dict(row) for row in application.marketing.external_sales(channel_id, limit)]}

    @app.post("/api/v1/admin/marketing/sales/external")
    def import_marketing_external_sale(payload: dict, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            sale = application.marketing.import_external_sale(**dict(payload or {}))
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"sale": dict(sale)}
