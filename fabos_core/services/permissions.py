"""Provider-independent RBAC permission service for FabOS."""


class PermissionService:
    PERMISSIONS = (
        "account.read", "account.manage", "customer.read", "customer.manage",
        "product.read", "product.manage", "quote.read", "quote.manage",
        "order.read", "order.manage", "payment.read", "payment.manage",
        "fulfillment.read", "fulfillment.manage", "production.read", "production.manage",
        "inventory.read", "inventory.manage", "design.read", "design.manage",
        "printer.read", "printer.manage", "notification.read", "notification.manage",
        "audit.read", "settings.manage",
    )

    ROLE_PERMISSIONS = {
        "customer": {
            "account.read", "customer.read", "quote.read", "order.read",
            "payment.read", "fulfillment.read", "notification.read",
        },
        "employee": set(PERMISSIONS) - {"account.manage", "settings.manage", "audit.read"},
        "administrator": set(PERMISSIONS),
    }

    def __init__(self, database):
        self.database = database

    def validate_permission(self, permission):
        if permission not in self.PERMISSIONS:
            raise ValueError("Unsupported permission")
        return permission

    def permissions_for_account_type(self, account_type):
        if account_type not in self.ROLE_PERMISSIONS:
            raise ValueError("Unsupported account type")
        return set(self.ROLE_PERMISSIONS[account_type])

    def permissions_for_user(self, user_id, account_type):
        permissions = self.permissions_for_account_type(account_type)
        try:
            with self.database.connect() as connection:
                rows = connection.execute(
                    "SELECT permission, allowed FROM user_permissions WHERE user_id=?",
                    (user_id,),
                ).fetchall()
        except Exception:
            rows = []
        for permission, allowed in rows:
            self.validate_permission(permission)
            if int(allowed):
                permissions.add(permission)
            else:
                permissions.discard(permission)
        return permissions

    def has_permission(self, account_type, permission, user_id=None):
        self.validate_permission(permission)
        if user_id is None:
            return permission in self.permissions_for_account_type(account_type)
        return permission in self.permissions_for_user(user_id, account_type)

    def require(self, account_type, permission, user_id=None):
        if not self.has_permission(account_type, permission, user_id=user_id):
            raise PermissionError("Permission denied: %s" % permission)
        return True

    def set_user_permission(self, user_id, permission, allowed):
        self.validate_permission(permission)
        value = 1 if allowed else 0
        with self.database.connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO permissions(key,name) VALUES(?,?)",
                (permission, permission),
            )
            row = connection.execute(
                "SELECT user_id FROM user_permissions WHERE user_id=? AND permission=?",
                (user_id, permission),
            ).fetchone()
            if row:
                connection.execute(
                    "UPDATE user_permissions SET allowed=? WHERE user_id=? AND permission=?",
                    (value, user_id, permission),
                )
            else:
                connection.execute(
                    "INSERT INTO user_permissions(user_id,permission,allowed) VALUES(?,?,?)",
                    (user_id, permission, value),
                )
            connection.commit()

    def clear_user_permission(self, user_id, permission):
        self.validate_permission(permission)
        with self.database.connect() as connection:
            connection.execute(
                "DELETE FROM user_permissions WHERE user_id=? AND permission=?",
                (user_id, permission),
            )
            connection.commit()

    def all_permissions(self):
        return tuple(self.PERMISSIONS)
