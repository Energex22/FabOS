"""Pass 20 authenticated security boundary shared by API and desktop callers.

This service does not own authentication or permissions. It composes the existing
AuthService, AccountService, and PermissionService so future API adapters have
one provider-independent place to resolve an authenticated actor and enforce a
permission before touching business services.
"""


class SecurityService:
    def __init__(self, database, auth, accounts, permissions):
        self.database = database
        self.auth = auth
        self.accounts = accounts
        self.permissions = permissions

    def authenticate(self, token):
        if not token:
            raise PermissionError("Authentication token is required")
        session = self.auth.authenticate(token)
        if not session:
            raise PermissionError("Authentication required")
        return session

    def actor(self, user_id):
        if not user_id:
            raise PermissionError("Authenticated user is required")
        user = self.accounts.get_user(user_id)
        if not user or not user["active"]:
            raise PermissionError("Authenticated user is inactive or not found")
        return user

    def require(self, user_id, permission):
        user = self.actor(user_id)
        self.permissions.require(user["account_type"], permission, user_id=user_id)
        return user

    def context(self, token, permission=None):
        session = self.authenticate(token)
        user = self.actor(session["user_id"])
        if permission:
            self.permissions.require(user["account_type"], permission, user_id=user["id"])
        return {"user": user, "session": session}

    def customer_scope(self, user_id, customer_id):
        user = self.actor(user_id)
        if user["account_type"] != "customer":
            return True
        customer = self.accounts.customer_for_user(user_id)
        return bool(customer and customer["id"] == customer_id)

    def order_scope(self, user_id, order_id):
        user = self.actor(user_id)
        if user["account_type"] != "customer":
            return True
        customer = self.accounts.customer_for_user(user_id)
        if not customer:
            return False
        with self.database.connect() as connection:
            return bool(connection.execute(
                "SELECT 1 FROM orders WHERE id=? AND customer_id=?",
                (order_id, customer["id"]),
            ).fetchone())

    def require_order_scope(self, user_id, order_id):
        if not self.order_scope(user_id, order_id):
            raise PermissionError("Order access denied")
        return True
