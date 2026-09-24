import uuid
from datetime import datetime


class FulfillmentService:
    """Fulfillment business service plus an actor-aware access boundary."""

    METHODS = ("pickup", "shipping")
    STATUSES = ("pending", "ready_for_pickup", "packed", "shipped", "delivered", "picked_up")
    TERMINAL_STATUSES = ("delivered", "picked_up")
    STATUS_ORDER = {"pending": 0, "ready_for_pickup": 1, "packed": 2, "shipped": 3, "delivered": 4, "picked_up": 4}

    def __init__(self, db, accounts=None, permissions=None):
        self.db = db
        self.accounts = accounts
        self.permissions = permissions

    def _user(self, user_id):
        if not user_id:
            raise PermissionError("Authenticated user is required")
        if self.accounts is None:
            from fabos_core.services.accounts import AccountService
            self.accounts = AccountService(self.db)
        user = self.accounts.get_user(user_id)
        if not user or not user["active"]:
            raise PermissionError("Authenticated user is inactive or not found")
        return user

    def _require(self, user_id, permission):
        user = self._user(user_id)
        if self.permissions is None:
            from fabos_core.services.permissions import PermissionService
            self.permissions = PermissionService(self.db)
        self.permissions.require(user["account_type"], permission, user_id=user_id)
        return user

    def _customer_fulfillment_allowed(self, user_id, fulfillment_id):
        user = self._user(user_id)
        if user["account_type"] != "customer":
            return True
        customer = self.accounts.customer_for_user(user_id)
        if not customer:
            return False
        with self.db.connect() as c:
            return bool(c.execute(
                """SELECT 1 FROM fulfillments f
                   JOIN orders o ON o.id=f.order_id
                   WHERE f.id=? AND o.customer_id=?""",
                (fulfillment_id, customer["id"]),
            ).fetchone())

    def _customer_order_allowed(self, user_id, order_id):
        user = self._user(user_id)
        if user["account_type"] != "customer":
            return True
        customer = self.accounts.customer_for_user(user_id)
        if not customer:
            return False
        with self.db.connect() as c:
            return bool(c.execute(
                "SELECT 1 FROM orders WHERE id=? AND customer_id=?",
                (order_id, customer["id"]),
            ).fetchone())

    def ensure(self, order_id, method="pickup"):
        method = str(method or "").strip().lower()
        if method not in self.METHODS:
            raise ValueError("Unsupported fulfillment method")
        with self.db.connect() as c:
            row = c.execute("SELECT * FROM fulfillments WHERE order_id=?", (order_id,)).fetchone()
            if row:
                return row["id"]
            if not c.execute("SELECT id FROM orders WHERE id=?", (order_id,)).fetchone():
                raise KeyError("Order not found.")
            fid = str(uuid.uuid4())
            c.execute(
                "INSERT INTO fulfillments(id,order_id,method,status) VALUES(?,?,?,'pending')",
                (fid, order_id, method),
            )
            c.commit()
            return fid

    def get_for_order(self, order_id):
        with self.db.connect() as c:
            return c.execute(
                "SELECT * FROM fulfillments WHERE order_id=?", (order_id,)
            ).fetchone()

    def get_for_user(self, user_id, fulfillment_id):
        self._require(user_id, "fulfillment.read")
        if not self._customer_fulfillment_allowed(user_id, fulfillment_id):
            raise PermissionError("Fulfillment access denied")
        with self.db.connect() as c:
            row = c.execute(
                """SELECT f.*,o.order_number,o.customer_id
                   FROM fulfillments f JOIN orders o ON o.id=f.order_id
                   WHERE f.id=?""",
                (fulfillment_id,),
            ).fetchone()
        if not row:
            raise KeyError("Fulfillment not found")
        return row

    def list_for_user(self, user_id, status="All"):
        user = self._require(user_id, "fulfillment.read")
        where = []
        args = []
        if status and status != "All":
            where.append("f.status=?")
            args.append(status.lower())
        if user["account_type"] == "customer":
            customer = self.accounts.customer_for_user(user_id)
            if not customer:
                return []
            where.append("o.customer_id=?")
            args.append(customer["id"])
        sql = """SELECT f.*,o.order_number,o.customer_id
                 FROM fulfillments f JOIN orders o ON o.id=f.order_id"""
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY f.updated_at DESC, f.id"
        with self.db.connect() as c:
            return c.execute(sql, args).fetchall()

    def ensure_for_user(self, user_id, order_id, method="pickup"):
        self._require(user_id, "fulfillment.manage")
        if not self._customer_order_allowed(user_id, order_id):
            raise PermissionError("Fulfillment access denied")
        return self.ensure(order_id, method)

    def save_for_user(self, user_id, order_id, method, status, carrier="", tracking="", weight_oz=None,
                      shipping_cost_cents=None, destination="", notes="", length_in=None, width_in=None,
                      height_in=None):
        self._require(user_id, "fulfillment.manage")
        if not self._customer_order_allowed(user_id, order_id):
            raise PermissionError("Fulfillment access denied")
        return self.save(order_id, method, status, carrier, tracking, weight_oz,
                         shipping_cost_cents, destination, notes, length_in, width_in, height_in)

    def save(self, order_id, method, status, carrier="", tracking="", weight_oz=None,
             shipping_cost_cents=None, destination="", notes="", length_in=None, width_in=None, height_in=None):
        method = str(method or "").strip().lower()
        status = str(status or "").strip().lower()
        if method not in self.METHODS:
            raise ValueError("Unsupported fulfillment method")
        if status not in self.STATUSES:
            raise ValueError("Unsupported fulfillment status")
        fid = self.ensure(order_id, method)
        with self.db.connect() as c:
            current = c.execute("SELECT method,status,shipping_cost_cents FROM fulfillments WHERE id=?", (fid,)).fetchone()
        current_status = str(current["status"] or "pending").lower() if current else "pending"
        if shipping_cost_cents is None:
            shipping_cost_cents = int(current["shipping_cost_cents"] or 0) if current else 0
        if self.STATUS_ORDER.get(status, 0) < self.STATUS_ORDER.get(current_status, 0):
            if current_status in self.TERMINAL_STATUSES:
                raise ValueError("Cannot move a completed fulfillment back to an earlier status")
            raise ValueError("Cannot move fulfillment back to an earlier status")
        if current and current["method"] != method and current_status != "pending":
            raise ValueError("Cannot change fulfillment method after fulfillment has started")
        now = datetime.now().isoformat(timespec="seconds")
        shipped = now if status == "shipped" else None
        delivered = now if status == "delivered" else None
        picked = now if status == "picked_up" else None
        with self.db.connect() as c:
            c.execute("""UPDATE fulfillments SET method=?,status=?,carrier=?,tracking_number=?,
              package_weight_oz=?,shipping_cost_cents=?,destination=?,notes=?,
              package_length_in=?,package_width_in=?,package_height_in=?,
              shipped_at=COALESCE(?,shipped_at),delivered_at=COALESCE(?,delivered_at),
              picked_up_at=COALESCE(?,picked_up_at),updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                      (method, status, carrier, tracking, weight_oz, int(shipping_cost_cents), destination, notes,
                       length_in, width_in, height_in, shipped, delivered, picked, fid))
            inv = c.execute("""SELECT id,subtotal_cents,tax_cents,discount_cents,paid_cents,status
              FROM invoices WHERE order_id=? AND status<>'void' ORDER BY created_at DESC LIMIT 1""", (order_id,)).fetchone()
            if inv:
                payment_table = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='payment_transactions'").fetchone()
                active_payment = None
                if payment_table:
                    active_payment = c.execute("SELECT 1 FROM payment_transactions WHERE invoice_id=? AND status IN ('created','pending','authorized','paid','partially_refunded') LIMIT 1", (inv["id"],)).fetchone()
                previous_shipping = int(c.execute("SELECT shipping_cents FROM invoices WHERE id=?", (inv["id"],)).fetchone()["shipping_cents"] or 0)
                if active_payment and int(shipping_cost_cents) != previous_shipping:
                    raise ValueError("Fulfillment shipping cost cannot change while a payment attempt is active.")
                total = max(0, int(inv['subtotal_cents'] or 0) + int(inv['tax_cents'] or 0) + int(shipping_cost_cents) - int(inv['discount_cents'] or 0))
                new_status = 'paid' if int(inv['paid_cents'] or 0) >= total and total > 0 else ('partial' if int(inv['paid_cents'] or 0) > 0 else 'open')
                c.execute("UPDATE invoices SET shipping_cents=?,total_cents=?,status=? WHERE id=?",
                          (int(shipping_cost_cents), total, new_status, inv['id']))
            if status == "shipped":
                c.execute("UPDATE orders SET status='shipped' WHERE id=?", (order_id,))
            elif status in ("delivered", "picked_up"):
                inv = c.execute("""SELECT * FROM invoices WHERE order_id=? AND status<>'void'
                                 ORDER BY created_at DESC LIMIT 1""", (order_id,)).fetchone()
                if inv and int(inv["paid_cents"] or 0) >= int(inv["total_cents"] or 0):
                    c.execute("UPDATE orders SET status='completed' WHERE id=?", (order_id,))
                else:
                    c.execute("UPDATE orders SET status='shipped' WHERE id=?", (order_id,))
            c.commit()
        return fid
