"""Administrator-only API routes for FabOS administration."""


def register_admin_routes(app, get_application, administrator_user, current_user=None):
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

    def operations_user(user=Depends(current_user) if current_user else Depends(administrator_user), application=Depends(get_application)):\n        if current_user is None:\n            return user\n        account_type = str(user["account_type"] or "").lower()\n        if account_type not in ("employee", "administrator"):\n            raise HTTPException(status_code=403, detail="Team account required")\n        if not application.permissions.has_permission(account_type, "production.read", user_id=user["id"]):\n            raise HTTPException(status_code=403, detail="Operations access denied")\n        return user\n\n    @app.get("/api/v1/admin/operations/dashboard")\n    def operations_dashboard(user=Depends(operations_user), application=Depends(get_application)):\n        from datetime import datetime, timedelta\n        now = datetime.now()\n        today = now.date().isoformat()\n        month_start = (now.date() - timedelta(days=29)).isoformat()\n        with application.database.connect() as conn:\n            def scalar(sql, args=()):\n                return conn.execute(sql, args).fetchone()[0] or 0\n\n            orders_today = int(scalar("SELECT COUNT(*) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')", (today,)))\n            sales_today = int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')", (today,)))\n            sales_30d = int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)>=date(?) AND status NOT IN ('cancelled')", (month_start,)))\n            active_orders = int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped')"))\n            active_jobs = int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('queued','scheduled','printing','paused')"))\n            printing_jobs = int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('printing','paused')"))\n            failed_jobs = int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status='failed'"))\n            printer_total = int(scalar("SELECT COUNT(*) FROM printers"))\n            printer_online = int(scalar("SELECT COUNT(*) FROM printers WHERE lower(COALESCE(status,'')) NOT IN ('offline','error')"))\n            low_filament_threshold = float(application.shop_settings.get("filament_low_threshold_g", "250") or 250)\n            low_filament = int(scalar("SELECT COUNT(*) FROM filament_spools WHERE active=1 AND remaining_g<?", (low_filament_threshold,)))\n            low_supplies = int(scalar("SELECT COUNT(*) FROM supply_items WHERE active=1 AND quantity<=low_threshold"))\n            open_quotes = int(scalar("SELECT COUNT(*) FROM quotes WHERE status IN ('draft','sent')"))\n            unpaid = int(scalar("SELECT COUNT(*) FROM invoices WHERE status IN ('open','partial')"))\n            overdue = int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped') AND due_at IS NOT NULL AND due_at<?", (today,)))\n            pending_qc = int(scalar("SELECT COUNT(*) FROM qc_inspections WHERE status='pending'"))\n\n            recent_orders = [dict(row) for row in conn.execute("""\n                SELECT o.id,o.order_number,o.status,o.total_cents,o.due_at,o.created_at,COALESCE(c.name,'No customer') customer_name\n                FROM orders o LEFT JOIN customers c ON c.id=o.customer_id\n                ORDER BY o.created_at DESC LIMIT 8""").fetchall()]\n            jobs = [dict(row) for row in conn.execute("""\n                SELECT j.id,j.status,j.estimated_minutes,j.print_time_left_seconds,COALESCE(p.name,'Custom Job') product_name,\n                       COALESCE(pr.name,'Unassigned') printer_name,COALESCE(o.order_number,'Personal') order_number,\n                       COALESCE(fs.material || ' ' || COALESCE(fs.color,''),'No spool') spool_name\n                FROM print_jobs j LEFT JOIN products p ON p.id=j.product_id LEFT JOIN printers pr ON pr.id=j.printer_id\n                LEFT JOIN orders o ON o.id=j.order_id LEFT JOIN filament_spools fs ON fs.id=j.spool_id\n                WHERE j.status IN ('queued','scheduled','printing','paused','failed')\n                ORDER BY CASE j.status WHEN 'failed' THEN 0 WHEN 'printing' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END,j.created_at LIMIT 12""").fetchall()]\n            printers = [dict(row) for row in conn.execute("""\n                SELECT id,name,model,status,connection_mode,simulation_progress,nozzle_temp,bed_temp,\n                       print_time_seconds,print_time_left_seconds,octoprint_state_text,octoprint_current_file,last_seen_at,total_hours\n                FROM printers ORDER BY name""").fetchall()]\n            low_spools = [dict(row) for row in conn.execute("""\n                SELECT id,material,brand,color,remaining_g,initial_g,cost_cents,location\n                FROM filament_spools WHERE active=1 AND remaining_g<? ORDER BY remaining_g LIMIT 10""",(low_filament_threshold,)).fetchall()]\n            maintenance = [dict(row) for row in conn.execute("""\n                SELECT p.id,p.name,p.total_hours,COALESCE(MAX(m.printer_hours),0) last_service_hours,\n                       p.total_hours-COALESCE(MAX(m.printer_hours),0) hours_since_service\n                FROM printers p LEFT JOIN maintenance_records m ON m.printer_id=p.id\n                GROUP BY p.id ORDER BY hours_since_service DESC""").fetchall()]\n\n        action_items=[]\n        try:\n            action_items=[dict(item) for item in application.operations_hub.action_items()[:20]]\n        except Exception:\n            pass\n        return {\n            "generated_at": now.isoformat(timespec="seconds"),\n            "viewer": {"id": user["id"], "account_type": user["account_type"], "role": user["role"]},\n            "business": {"orders_today": orders_today, "sales_today_cents": sales_today, "sales_30d_cents": sales_30d, "active_orders": active_orders, "open_quotes": open_quotes, "unpaid_invoices": unpaid, "overdue_orders": overdue, "pending_qc": pending_qc},\n            "production": {"active_jobs": active_jobs, "printing_jobs": printing_jobs, "failed_jobs": failed_jobs, "jobs": jobs},\n            "printers": {"total": printer_total, "online": printer_online, "items": printers},\n            "inventory": {"low_filament": low_filament, "low_supplies": low_supplies, "filament_threshold_g": low_filament_threshold, "spools": low_spools},\n            "maintenance": {"items": maintenance},\n            "recent_orders": recent_orders,\n            "action_items": action_items,\n        }\n\n    @app.get("/api/v1/admin/users")
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
