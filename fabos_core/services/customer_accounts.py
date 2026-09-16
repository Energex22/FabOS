"""Customer account registration boundary for the public storefront."""
import uuid


class CustomerAccountService:
    def __init__(self, database, accounts, auth):
        self.database = database
        self.accounts = accounts
        self.auth = auth

    def register(self, name, email, password, phone=""):
        name = (name or "").strip()
        email = (email or "").strip().lower()
        if not name:
            raise ValueError("Name is required")
        if not email or "@" not in email:
            raise ValueError("A valid email is required")
        self.auth.hash_password(password)
        if self.accounts.get_by_email(email):
            raise ValueError("An account with that email already exists")
        user_id = str(uuid.uuid4())
        customer_id = str(uuid.uuid4())
        password_hash = self.auth.hash_password(password)
        with self.database.connect() as conn:
            conn.execute("INSERT INTO users(id,username,password_hash,role,active,email,account_type,updated_at) VALUES(?,?,?,?,1,?,?,CURRENT_TIMESTAMP)", (user_id, email, password_hash, "customer", email, "customer"))
            conn.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)", (customer_id, name, email, (phone or "").strip(), ""))
            conn.execute("INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)", (user_id, customer_id))
            conn.commit()
        return self.auth.login(email, password)
