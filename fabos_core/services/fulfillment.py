import logging
import uuid
from datetime import datetime, timedelta
from urllib.parse import quote as _url_quote

from fabos_core.services.customer_notifications import CustomerNotificationService

logger = logging.getLogger(__name__)


# Public package-tracking URL patterns by carrier. The carrier name is matched
# case-insensitively as a substring; unknown carriers yield no URL (None).
_TRACKING_URL_PATTERNS = (
    ("ups", "https://www.ups.com/track?tracknum={number}"),
    ("fedex", "https://www.fedex.com/fedextrack/?trknbr={number}"),
    ("usps", "https://tools.usps.com/go/TrackConfirmAction?tLabels={number}"),
    ("dhl", "https://www.dhl.com/us-en/home/tracking/tracking-express.html?submit=1&tracking-id={number}"),
)

# Typical carrier ground-transit windows (calendar days). Used only to sketch
# an estimated delivery date from shipped_at until real carrier ETA data is
# wired in; unknown carriers fall back to 5 days.
_CARRIER_TRANSIT_DAYS = {"ups": 5, "fedex": 5, "usps": 4, "dhl": 3}
_DEFAULT_TRANSIT_DAYS = 5


class FulfillmentService:
    """Fulfillment business service plus an actor-aware access boundary."""

    METHODS = ("pickup", "shipping")
    STATUSES = ("pending", "ready_for_pickup", "packed", "shipped", "delivered", "picked_up")
    TERMINAL_STATUSES = ("delivered", "picked_up")
    STATUS_ORDER = {"pending": 0, "ready_for_pickup": 1, "packed": 2, "shipped": 3, "delivered": 4, "picked_up": 4}
    # Explicit state machine for the admin transition endpoint. Shipping flows
    # packed -> shipped -> delivered; pickup flows pending -> ready_for_pickup
    # -> picked_up. packed -> ready_for_pickup is the one sanctioned
    # conversion (a packed order the customer ends up collecting in person);
    # it flips the method to pickup as part of the transition. Anything not
    # listed here — including skipping steps like packed -> delivered — is
    # rejected with a clear 400.
    TRANSITION_EDGES = {
        "pending": ("packed", "ready_for_pickup"),
        "packed": ("shipped", "ready_for_pickup"),
        "ready_for_pickup": ("picked_up",),
        "shipped": ("delivered",),
        "delivered": (),
        "picked_up": (),
    }
    _SHIPPING_ONLY_STATUSES = ("packed", "shipped", "delivered")
    _PICKUP_ONLY_STATUSES = ("ready_for_pickup", "picked_up")

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

    @staticmethod
    def tracking_url(carrier, tracking_number):
        """Public tracking URL for a carrier + tracking number, or None."""
        number = str(tracking_number or "").strip()
        if not number:
            return None
        name = str(carrier or "").lower()
        for key, pattern in _TRACKING_URL_PATTERNS:
            if key in name:
                return pattern.format(number=_url_quote(number, safe=""))
        return None

    @staticmethod
    def estimated_delivery(fulfillment):
        """Rough delivery date: shipped_at + carrier typical transit.

        A sketch only (calendar days, no weekends/holidays), meant to power
        the customer "Track your package" card until real carrier ETA data is
        wired in. Returns an ISO date string or None.
        """
        row = dict(fulfillment or {})
        shipped = row.get("shipped_at")
        if not shipped or row.get("delivered_at"):
            return None
        name = str(row.get("carrier") or "").lower()
        days = next((d for key, d in _CARRIER_TRANSIT_DAYS.items() if key in name),
                    _DEFAULT_TRANSIT_DAYS)
        try:
            dt = datetime.fromisoformat(str(shipped))
        except ValueError:
            return None
        return (dt + timedelta(days=days)).date().isoformat()

    @classmethod
    def customer_payload(cls, fulfillment):
        """Customer-safe fulfillment object for the order payload.

        Every key is always present; unknown values are null, never omitted.
        """
        row = dict(fulfillment or {})

        def _nullish(key):
            value = row.get(key)
            if value is None:
                return None
            text = str(value).strip()
            return text if text else None

        carrier = _nullish("carrier")
        tracking = _nullish("tracking_number")
        return {
            "carrier": carrier,
            "tracking_number": tracking,
            "tracking_url": cls.tracking_url(carrier, tracking),
            "method": _nullish("method"),
            "status": _nullish("status"),
            "packed_at": _nullish("packed_at"),
            "shipped_at": _nullish("shipped_at"),
            "delivered_at": _nullish("delivered_at"),
            "picked_up_at": _nullish("picked_up_at"),
            "estimated_delivery": cls.estimated_delivery(row),
        }

    def _get(self, fulfillment_id):
        with self.db.connect() as c:
            row = c.execute(
                """SELECT f.*,o.order_number,o.customer_id,o.status AS order_status
                   FROM fulfillments f JOIN orders o ON o.id=f.order_id
                   WHERE f.id=?""",
                (fulfillment_id,),
            ).fetchone()
        if not row:
            raise KeyError("Fulfillment not found")
        return row

    @staticmethod
    def _derive_method_from_order_row(order):
        """Derive the fulfillment method from the order's shipping data.

        Orders that paid for shipping (shipping_cents > 0) or carry a real
        shipping address are shipping orders; staff/internal orders with
        neither default to pickup. Staff can still correct the method with
        the admin PATCH endpoint before fulfillment advances.
        """
        if not order:
            raise KeyError("Order not found.")
        cents = int(order["shipping_cents"] or 0) if "shipping_cents" in order.keys() else 0
        address = str(order["shipping_address_json"] or "").strip() if "shipping_address_json" in order.keys() else ""
        if cents > 0 or address not in ("", "{}"):
            return "shipping"
        return "pickup"

    def derive_method(self, order_id):
        """Derive the initial fulfillment method for an order (Phase 4)."""
        with self.db.connect() as c:
            order = c.execute(
                "SELECT shipping_cents,shipping_address_json FROM orders WHERE id=?",
                (order_id,)).fetchone()
        return self._derive_method_from_order_row(order)

    def ensure(self, order_id, method=None):
        if method is None:
            method = self.derive_method(order_id)
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

    def ensure_for_user(self, user_id, order_id, method=None):
        self._require(user_id, "fulfillment.manage")
        if not self._customer_order_allowed(user_id, order_id):
            raise PermissionError("Fulfillment access denied")
        return self.ensure(order_id, method)

    def update_for_user(self, user_id, fulfillment_id, method=None, carrier=None,
                        tracking_number=None, destination=None):
        """Admin edit of fulfillment fields (Phase 4 PATCH endpoint).

        Only supplied fields change. The method may only change while the
        fulfillment is still pending (it must stay compatible with the
        current status otherwise); save() re-validates the combination.
        Returns the updated fulfillment as a plain dict.
        """
        self._require(user_id, "fulfillment.manage")
        row = self._get(fulfillment_id)
        current_status = str(row["status"] or "pending").lower()
        if method is not None:
            new_method = str(method).strip().lower()
            if new_method not in self.METHODS:
                raise ValueError("Unsupported fulfillment method '%s'. Use pickup or shipping." % (method,))
        else:
            new_method = str(row["method"] or "pickup").lower()
        for label, value, cap in (("carrier", carrier, 120),
                                  ("tracking_number", tracking_number, 120),
                                  ("destination", destination, 500)):
            if value is not None and len(str(value)) > cap:
                raise ValueError("%s is too long (maximum %d characters)." % (label, cap))
        fid = self.save(
            row["order_id"], new_method, current_status,
            carrier=row["carrier"] if carrier is None else str(carrier or "").strip(),
            tracking=row["tracking_number"] if tracking_number is None else str(tracking_number or "").strip(),
            weight_oz=row["package_weight_oz"],
            shipping_cost_cents=row["shipping_cost_cents"],
            destination=row["destination"] if destination is None else str(destination or "").strip(),
            notes=row["notes"] or "",
            length_in=row["package_length_in"],
            width_in=row["package_width_in"],
            height_in=row["package_height_in"],
        )
        return dict(self._get(fid))

    def transition_for_user(self, user_id, fulfillment_id, to_state):
        """Admin state transition (Phase 4 POST .../transition endpoint).

        Only the edges in TRANSITION_EDGES are allowed — no skipping steps
        (packed -> delivered is rejected) and no method-incompatible states.
        packed -> ready_for_pickup flips the method to pickup as part of the
        transition (a packed order the customer collects in person). The
        shipped transition fires the Phase 2 order_shipped notification via
        save(). Returns the updated fulfillment as a plain dict.
        """
        self._require(user_id, "fulfillment.manage")
        to_state = str(to_state or "").strip().lower()
        if to_state not in self.STATUSES:
            raise ValueError("Unknown fulfillment status '%s'." % (to_state,))
        row = self._get(fulfillment_id)
        current = str(row["status"] or "pending").lower()
        method = str(row["method"] or "pickup").lower()
        if to_state == current:
            raise ValueError("Fulfillment is already '%s'." % current)
        allowed = self.TRANSITION_EDGES.get(current, ())
        if to_state not in allowed:
            detail = ", ".join(allowed) if allowed else "none — this fulfillment is complete"
            raise ValueError(
                "Cannot transition fulfillment from '%s' to '%s'. Valid next states: %s."
                % (current, to_state, detail))
        if to_state in self._SHIPPING_ONLY_STATUSES and method != "shipping":
            raise ValueError(
                "Cannot mark '%s' on a pickup fulfillment. Change the method to shipping first."
                % to_state)
        if to_state in self._PICKUP_ONLY_STATUSES and method != "pickup":
            if current == "packed" and to_state == "ready_for_pickup":
                # Sanctioned conversion: the packed order will be collected
                # in person, so the method flips to pickup with the state.
                method = "pickup"
            else:
                raise ValueError(
                    "Cannot mark '%s' on a shipping fulfillment. Change the method to pickup first."
                    % to_state)
        fid = self.save(
            row["order_id"], method, to_state,
            carrier=row["carrier"] or "",
            tracking=row["tracking_number"] or "",
            weight_oz=row["package_weight_oz"],
            shipping_cost_cents=row["shipping_cost_cents"],
            destination=row["destination"] or "",
            notes=row["notes"] or "",
            length_in=row["package_length_in"],
            width_in=row["package_width_in"],
            height_in=row["package_height_in"],
        )
        return dict(self._get(fid))

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
        if method == "shipping" and status in ("ready_for_pickup", "picked_up"):
            raise ValueError("Shipping fulfillment cannot use pickup-only status.")
        if method == "pickup" and status in ("packed", "shipped", "delivered"):
            raise ValueError("Pickup fulfillment cannot use shipping-only status.")
        fid = self.ensure(order_id, method)
        with self.db.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            current = c.execute("SELECT method,status,shipping_cost_cents FROM fulfillments WHERE id=?", (fid,)).fetchone()
        current_status = str(current["status"] or "pending").lower() if current else "pending"
        with self.db.connect() as c:
            order = c.execute("SELECT status FROM orders WHERE id=?", (order_id,)).fetchone()
        order_status = str(order["status"] or "").lower() if order else ""
        if status in ("packed", "shipped", "delivered", "picked_up"):
            if order_status not in ("ready", "shipped"):
                raise ValueError("Order must be QC-approved and ready before fulfillment can advance.")
            # Do not rely solely on the mutable order status as proof of QC. An
            # admin/import path can move an order to ready directly, so fulfillment
            # must independently enforce the production/QC boundary.
            with self.db.connect() as c:
                all_jobs = c.execute(
                    "SELECT status FROM print_jobs WHERE order_id=?",
                    (order_id,),
                ).fetchall()
                jobs = [row for row in all_jobs if str(row["status"] or "").lower() != "cancelled"]
                if all_jobs and not jobs:
                    raise ValueError("Order must have an active production job before fulfillment can advance.")
                if jobs:
                    if any(str(row["status"] or "").lower() != "completed" for row in jobs):
                        raise ValueError("Order must be QC-approved and all active production jobs completed before fulfillment can advance.")
                    missing_qc = c.execute(
                        """SELECT 1
                           FROM print_jobs j
                           WHERE j.order_id=? AND COALESCE(j.status,'')<>'cancelled'
                             AND NOT EXISTS (
                                 SELECT 1 FROM qc_inspections q
                                 WHERE q.order_id=j.order_id
                                   AND q.print_job_id=j.id
                                   AND LOWER(COALESCE(q.status,''))='passed'
                             )
                           LIMIT 1""",
                        (order_id,),
                    ).fetchone()
                    if missing_qc:
                        raise ValueError("Order must be QC-approved and every active production job must have a passed inspection before fulfillment can advance.")
        if shipping_cost_cents is None:
            shipping_cost_cents = int(current["shipping_cost_cents"] or 0) if current else 0
        if self.STATUS_ORDER.get(status, 0) < self.STATUS_ORDER.get(current_status, 0):
            if current_status in self.TERMINAL_STATUSES:
                raise ValueError("Cannot move a completed fulfillment back to an earlier status")
            if not (current_status == "packed" and status == "ready_for_pickup"):
                # packed -> ready_for_pickup is the one sanctioned backward
                # conversion (a packed order collected in person); everything
                # else must move forward through the state machine.
                raise ValueError("Cannot move fulfillment back to an earlier status")
        if current and current["method"] != method and current_status != "pending":
            if not (current_status == "packed" and status == "ready_for_pickup" and method == "pickup"):
                raise ValueError("Cannot change fulfillment method after fulfillment has started")
        now = datetime.now().isoformat(timespec="seconds")
        packed = now if status == "packed" else None
        shipped = now if status == "shipped" else None
        delivered = now if status == "delivered" else None
        picked = now if status == "picked_up" else None
        with self.db.connect() as c:
            c.execute("""UPDATE fulfillments SET method=?,status=?,carrier=?,tracking_number=?,
              package_weight_oz=?,shipping_cost_cents=?,destination=?,notes=?,
              package_length_in=?,package_width_in=?,package_height_in=?,
              packed_at=COALESCE(?,packed_at),shipped_at=COALESCE(?,shipped_at),delivered_at=COALESCE(?,delivered_at),
              picked_up_at=COALESCE(?,picked_up_at),updated_at=CURRENT_TIMESTAMP WHERE id=?""",
                      (method, status, carrier, tracking, weight_oz, int(shipping_cost_cents), destination, notes,
                       length_in, width_in, height_in, packed, shipped, delivered, picked, fid))
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
                # Shipping reaches the shipped order state before attempting central
                # completion; pickup remains in ready until the completion gate passes.
                if method == "shipping":
                    c.execute("UPDATE orders SET status='shipped' WHERE id=? AND status='ready'", (order_id,))
            c.commit()

        if status in ("delivered", "picked_up"):
            from fabos_core.services.orders import OrderService
            try:
                OrderService(self.db).set_status_internal(order_id, "completed", reason="Fulfillment completed")
            except ValueError:
                # A completed fulfillment is still recorded even when another
                # completion gate (payment/production/QC) remains outstanding.
                pass
        if status == "shipped" and current_status != "shipped":
            # The customer-facing shipped notification carries carrier +
            # tracking. Dedupe key makes repeat saves idempotent.
            try:
                with self.db.connect() as c:
                    order = c.execute(
                        "SELECT id,order_number,customer_id FROM orders WHERE id=?",
                        (order_id,)).fetchone()
                if order:
                    CustomerNotificationService(self.db).notify_order_shipped(
                        dict(order),
                        {"id": fid, "carrier": carrier, "tracking_number": tracking})
            except Exception:
                logger.exception("order_shipped notification hook failed for order %s", order_id)
        return fid
