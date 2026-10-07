"""Customer account registration boundary for the public storefront."""
import sqlite3
import uuid


class CustomerAccountService:
    def __init__(self, database, accounts, auth, shop_settings=None):
        self.database = database
        self.accounts = accounts
        self.auth = auth
        self.shop_settings = shop_settings

    def register(self, name, email, password, phone=""):
        name = (name or "").strip()
        email = (email or "").strip().lower()
        if not name:
            raise ValueError("Name is required")
        if not email or "@" not in email:
            raise ValueError("A valid email is required")
        if self.shop_settings is not None:
            if str(self.shop_settings.get("storefront_enabled", "true")).lower() != "true":
                raise PermissionError("Storefront is currently unavailable")
            if str(self.shop_settings.get("customer_registration_enabled", "true")).lower() != "true":
                raise PermissionError("Customer registration is currently disabled")
        if self.accounts.get_by_email(email):
            raise ValueError("An account with that email already exists")
        user_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())
        password_hash = self.auth.hash_password(password)
        try:
            with self.database.connect() as conn:
                conn.execute("INSERT INTO users(id,username,password_hash,role,active,email,account_type,updated_at) VALUES(?,?,?,?,1,?,?,CURRENT_TIMESTAMP)", (user_id, email, password_hash, "customer", email, "customer"))
                conn.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", (customer_id, name, email, (phone or "").strip(), ""))
                conn.execute("INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)", (user_id, customer_id))
                conn.commit()
        except sqlite3.IntegrityError as exc:
            # The get_by_email pre-check races with concurrent registrations.
            # Re-check before reporting: only a genuine duplicate becomes a
            # graceful 409, anything else still surfaces as an error.
            if self.accounts.get_by_email(email):
                raise ValueError("An account with that email already exists") from exc
            raise
        return self.auth.login(email, password)
