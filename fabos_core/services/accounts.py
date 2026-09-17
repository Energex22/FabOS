"""Identity/account foundation for FabOS.

This service deliberately does not authenticate users or enforce permissions yet.
It provides the stable account/customer/employee relationships that later auth and
RBAC layers can build on without replacing the existing users table.
"""


class AccountService:
    ACCOUNT_TYPES = ("customer", "employee", "administrator")

    def __init__(self, database):
        self.database = database

    def get_user(self, user_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    def get_by_username(self, username):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()

    def get_by_email(self, email):
        value = (email or "").strip().lower()
        if not value:
            return None
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM users WHERE lower(email)=?", (value,)).fetchone()

    def list_users(self, account_type=None, active_only=False):
        where = []
        args = []
        if account_type:
            if account_type not in self.ACCOUNT_TYPES:
                raise ValueError("Unsupported account type")
            where.append("account_type=?")
            args.append(account_type)
        if active_only:
            where.append("active=1")
        sql = "SELECT * FROM users"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY username COLLATE NOCASE"
        with self.database.connect() as conn:
            return conn.execute(sql, args).fetchall()

    def update_account(self, user_id, email=None, account_type=None, active=None):
        if account_type is not None and account_type not in self.ACCOUNT_TYPES:
            raise ValueError("Unsupported account type")
        changes = []
        args = []
        if email is not None:
            value = email.strip().lower()
            changes.append("email=?")
            args.append(value or None)
        if account_type is not None:
            changes.append("account_type=?")
            args.append(account_type)
        if active is not None:
            changes.append("active=?")
            args.append(1 if active else 0)
        if not changes:
            return self.get_user(user_id)
        changes.append("updated_at=CURRENT_TIMESTAMP")
        args.append(user_id)
        with self.database.connect() as conn:
            current = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not current:
                raise KeyError("User not found")
            current_type = str(current["account_type"] or "").lower()
            current_active = bool(current["active"])
            resulting_type = account_type if account_type is not None else current_type
            resulting_active = bool(active) if active is not None else current_active
            current_role = str(current["role"] or "").lower() if "role" in current.keys() else ""
            if current_role == "owner" and (
                resulting_type != "administrator" or not resulting_active
            ):
                raise ValueError("Cannot disable or demote the owner account")
            if current_role == "owner" and account_type is not None and resulting_type == "administrator":
                # The owner role is intentionally not editable through the generic
                # account service; owner status is a protected security boundary.
                raise ValueError("Cannot change the owner account through account management")
            if current_type == "administrator" and current_active and (
                resulting_type != "administrator" or not resulting_active
            ):
                other_admin = conn.execute(
                    "SELECT 1 FROM users WHERE account_type='administrator' AND active=1 AND id<>? LIMIT 1",
                    (user_id,),
                ).fetchone()
                if not other_admin:
                    raise ValueError("Cannot disable or demote the last active administrator")
            cur = conn.execute("UPDATE users SET " + ",".join(changes) + " WHERE id=?", args)
            if cur.rowcount != 1:
                raise KeyError("User not found")
            conn.commit()
        return self.get_user(user_id)

    def link_customer(self, user_id, customer_id):
        with self.database.connect() as conn:
            if not conn.execute("SELECT 1 FROM users WHERE id=?", (user_id,)).fetchone():
                raise KeyError("User not found")
            if not conn.execute("SELECT 1 FROM customers WHERE id=?", (customer_id,)).fetchone():
                raise KeyError("Customer not found")
            existing_user = conn.execute(
                "SELECT user_id FROM customer_accounts WHERE customer_id=? AND user_id<>?",
                (customer_id, user_id),
            ).fetchone()
            if existing_user:
                raise ValueError("Customer is already linked to another user")
            existing_link = conn.execute(
                "SELECT user_id FROM customer_accounts WHERE user_id=?", (user_id,)
            ).fetchone()
            if existing_link:
                conn.execute(
                    "UPDATE customer_accounts SET customer_id=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                    (customer_id, user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)",
                    (user_id, customer_id),
                )
            conn.execute(
                "UPDATE users SET account_type='customer',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (user_id,),
            )
            conn.commit()
        return self.customer_for_user(user_id)

    def customer_for_user(self, user_id):
        with self.database.connect() as conn:
            return conn.execute(
                "SELECT c.* FROM customers c JOIN customer_accounts ca ON ca.customer_id=c.id WHERE ca.user_id=?",
                (user_id,),
            ).fetchone()

    def set_employee_profile(self, user_id, department=None, position=None, employment_status="active", metadata_json="{}"):
        if not self.get_user(user_id):
            raise KeyError("User not found")
        if not employment_status:
            employment_status = "active"
        with self.database.connect() as conn:
            existing_profile = conn.execute(
                "SELECT user_id FROM employee_profiles WHERE user_id=?", (user_id,)
            ).fetchone()
            if existing_profile:
                conn.execute(
                    "UPDATE employee_profiles SET department=?,position=?,employment_status=?,metadata_json=?,updated_at=CURRENT_TIMESTAMP WHERE user_id=?",
                    (department, position, employment_status, metadata_json, user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO employee_profiles(user_id,department,position,employment_status,metadata_json,updated_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP)",
                    (user_id, department, position, employment_status, metadata_json),
                )
            conn.execute(
                "UPDATE users SET account_type='employee',updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (user_id,),
            )
            conn.commit()
        return self.employee_for_user(user_id)

    def employee_for_user(self, user_id):
        with self.database.connect() as conn:
            return conn.execute("SELECT * FROM employee_profiles WHERE user_id=?", (user_id,)).fetchone()

    def account_summary(self, user_id):
        user = self.get_user(user_id)
        if not user:
            raise KeyError("User not found")
        customer = self.customer_for_user(user_id)
        employee = self.employee_for_user(user_id)
        return {"user": user, "customer": customer, "employee": employee}
