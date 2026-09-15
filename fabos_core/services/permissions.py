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

    def has_permission(self, account_type, permission):
        self.validate_permission(permission)
        return permission in self.permissions_for_account_type(account_type)

    def require(self, account_type, permission):
        if not self.has_permission(account_type, permission):
            raise PermissionError("Permission denied: %s" % permission)
        return True

    def all_permissions(self):
        return tuple(self.PERMISSIONS)
