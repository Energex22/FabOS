"""Administrator-only API routes for FabOS administration."""


def register_admin_routes(app, get_application, administrator_user):
    from fastapi import Depends, HTTPException
    from pydantic import BaseModel, Field

    class AccountUpdate(BaseModel):
        email: str | None = Field(default=None, max_length=320)
        account_type: str | None = Field(default=None, max_length=30)
        active: bool | None = None

    class PasswordReset(BaseModel):
        password: str = Field(min_length=8, max_length=1024)

    class PermissionUpdate(BaseModel):
        allowed: bool

    class SettingUpdate(BaseModel):
        key: str = Field(min_length=1, max_length=100)
        value: str = Field(default="", max_length=4000)

    def admin(application, user):
        return application, user

    @app.get("/api/v1/admin/users")
    def list_admin_users(user=Depends(administrator_user), application=Depends(get_application)):
        rows = application.accounts.list_users()
        users = []
        for row in rows:
            item = {key: row[key] for key in ("id", "username", "email", "account_type", "active", "created_at", "updated_at", "last_login_at") if key in row.keys()}
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
            "user": {key: row[key] for key in ("id", "username", "email", "account_type", "active", "created_at", "updated_at", "last_login_at") if key in row.keys()},
            "customer": summary.get("customer"),
            "employee": summary.get("employee"),
            "permissions": sorted(application.permissions.permissions_for_user(user_id, row["account_type"])),
        }

    @app.patch("/api/v1/admin/users/{user_id}")
    def update_admin_user(user_id: str, payload: AccountUpdate, user=Depends(administrator_user), application=Depends(get_application)):
        row = application.accounts.get_user(user_id)
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        values = payload.model_dump(exclude_unset=True)
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
        if not application.accounts.get_user(user_id):
            raise HTTPException(status_code=404, detail="User not found")
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
        if not application.accounts.get_user(user_id):
            raise HTTPException(status_code=404, detail="User not found")
        try:
            application.permissions.set_user_permission(user_id, permission, payload.allowed)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated": True, "permission": permission, "allowed": payload.allowed}

    @app.delete("/api/v1/admin/users/{user_id}/permissions/{permission}")
    def clear_user_permission(user_id: str, permission: str, user=Depends(administrator_user), application=Depends(get_application)):
        if not application.accounts.get_user(user_id):
            raise HTTPException(status_code=404, detail="User not found")
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
        try:
            application.shop_settings.set_validated(payload.key, payload.value)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"key": payload.key, "value": application.shop_settings.get(payload.key), "metadata": application.shop_settings.metadata().get(payload.key)}
