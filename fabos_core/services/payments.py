"""Provider-neutral payment orchestration for FabOS.

FabOS owns the order/payment record while gateway adapters own provider-specific
HTTP calls and webhook verification. Card data is never stored in FabOS.
"""
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
import uuid


class PaymentProviderNotConfigured(RuntimeError):
    pass


class PaymentProviderError(RuntimeError):
    pass


class PaymentProvider:
    name = "base"

    def create_checkout(self, *, payment_id, amount_cents, currency, metadata):
        raise NotImplementedError

    def parse_webhook(self, payload, signature=None):
        raise NotImplementedError


class UnconfiguredPaymentProvider(PaymentProvider):
    name = "unconfigured"

    def create_checkout(self, *, payment_id, amount_cents, currency, metadata):
        raise PaymentProviderNotConfigured("No payment provider is configured")

    def parse_webhook(self, payload, signature=None):
        raise PaymentProviderNotConfigured("No payment provider is configured")


class StripePaymentProvider(PaymentProvider):
    name = "stripe"
    api_base = "https://api.stripe.com/v1"

    def __init__(self):
        self.secret_key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
        self.webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
        if not self.secret_key:
            raise PaymentProviderNotConfigured("STRIPE_SECRET_KEY is not configured")

    def _request(self, path, fields):
        body = urllib.parse.urlencode(fields).encode("utf-8")
        request = urllib.request.Request(
            self.api_base + path,
            data=body,
            method="POST",
            headers={
                "Authorization": "Bearer " + self.secret_key,
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "FabOS/1.0",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise PaymentProviderError("Stripe request failed") from exc

    def create_checkout(self, *, payment_id, amount_cents, currency, metadata):
        success_url = os.environ.get("STRIPE_SUCCESS_URL", "").strip()
        cancel_url = os.environ.get("STRIPE_CANCEL_URL", "").strip()
        if not success_url or not cancel_url:
            raise PaymentProviderNotConfigured("STRIPE_SUCCESS_URL and STRIPE_CANCEL_URL are required")
        fields = {
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "line_items[0][price_data][currency]": currency.lower(),
            "line_items[0][price_data][product_data][name]": "FabOS order " + str(metadata["order_id"]),
            "line_items[0][price_data][unit_amount]": str(int(amount_cents)),
            "line_items[0][quantity]": "1",
            "client_reference_id": str(metadata["order_id"]),
            "metadata[payment_id]": str(payment_id),
            "metadata[order_id]": str(metadata["order_id"]),
        }
        session = self._request("/checkout/sessions", fields)
        return {
            "provider_payment_id": session.get("payment_intent") or session.get("id"),
            "checkout_url": session.get("url"),
            "status": "pending",
            "metadata": {**metadata, "stripe_session_id": session.get("id")},
        }

    def parse_webhook(self, payload, signature=None):
        if not self.webhook_secret:
            raise PaymentProviderNotConfigured("STRIPE_WEBHOOK_SECRET is not configured")
        if not signature:
            raise PaymentProviderError("Missing Stripe webhook signature")
        _verify_stripe_signature(payload, signature, self.webhook_secret)
        event = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        event_type = str(event.get("type") or "")
        obj = ((event.get("data") or {}).get("object") or {})
        metadata = obj.get("metadata") or {}
        status = None
        if event_type in {"checkout.session.completed", "payment_intent.succeeded", "charge.succeeded"}:
            status = "paid"
        elif event_type in {"payment_intent.payment_failed", "charge.failed"}:
            status = "failed"
        elif event_type == "checkout.session.expired":
            status = "cancelled"
        elif event_type in {"charge.refunded", "refund.created"}:
            status = "refunded"
        return {
            "event_id": str(event.get("id") or ""),
            "event_type": event_type,
            "provider_payment_id": str(obj.get("payment_intent") or obj.get("id") or ""),
            "payment_id": str(metadata.get("payment_id") or ""),
            "order_id": str(metadata.get("order_id") or ""),
            "status": status,
        }


def _verify_stripe_signature(payload, signature, secret, tolerance=300):
    """Verify Stripe's v1 timestamped HMAC signature without a dependency."""
    timestamp = None
    signatures = []
    for part in str(signature).split(","):
        key, _, value = part.partition("=")
        if key == "t":
            timestamp = value
        elif key == "v1" and value:
            signatures.append(value)
    if not timestamp or not signatures:
        raise PaymentProviderError("Invalid Stripe webhook signature")
    try:
        timestamp_int = int(timestamp)
    except ValueError as exc:
        raise PaymentProviderError("Invalid Stripe webhook timestamp") from exc
    if abs(int(time.time()) - timestamp_int) > tolerance:
        raise PaymentProviderError("Expired Stripe webhook signature")
    signed_payload = "%s.%s" % (timestamp, payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    expected = hmac.new(secret.encode("utf-8"), signed_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not any(hmac.compare_digest(expected, value) for value in signatures):
        raise PaymentProviderError("Invalid Stripe webhook signature")


class PaymentService:
    """Persist payment attempts and delegate gateway work to a provider adapter."""

    VALID_STATUSES = {"created", "pending", "authorized", "paid", "failed", "cancelled", "refunded", "partially_refunded", "disputed"}

    def __init__(self, database, accounts, invoices):
        self.database = database
        self.accounts = accounts
        self.invoices = invoices
        self._ensure_schema()
        self.provider = self._build_provider()

    def _ensure_schema(self):
        with self.database.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS payment_transactions(
                id TEXT PRIMARY KEY,
                order_id TEXT NOT NULL UNIQUE REFERENCES orders(id) ON DELETE CASCADE,
                invoice_id TEXT REFERENCES invoices(id) ON DELETE SET NULL,
                customer_id TEXT REFERENCES customers(id) ON DELETE SET NULL,
                amount_cents INTEGER NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                provider TEXT NOT NULL,
                provider_payment_id TEXT,
                checkout_url TEXT,
                status TEXT NOT NULL DEFAULT 'created',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_transactions_customer ON payment_transactions(customer_id,created_at)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_payment_transactions_status ON payment_transactions(status,created_at)")
            conn.execute("""CREATE TABLE IF NOT EXISTS payment_webhook_events(
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL,
                event_type TEXT,
                payment_id TEXT,
                received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()

    def _build_provider(self):
        name = os.environ.get("FABOS_PAYMENT_PROVIDER", "none").strip().lower()
        if name in ("", "none", "unconfigured"):
            return UnconfiguredPaymentProvider()
        if name == "stripe":
            return StripePaymentProvider()
        raise ValueError("Unsupported payment provider: %s" % name)

    def _customer_for_order(self, user_id, order_id):
        user = self.accounts.get_user(user_id)
        if not user or not user["active"] or user["account_type"] != "customer":
            raise PermissionError("Customer account required")
        customer = self.accounts.customer_for_user(user_id)
        if not customer:
            raise PermissionError("Customer account is not linked to a customer record")
        with self.database.connect() as conn:
            order = conn.execute("SELECT * FROM orders WHERE id=? AND customer_id=?", (order_id, customer["id"])).fetchone()
        if not order:
            raise KeyError("Order not found")
        return customer, order

    def create_checkout(self, user_id, order_id):
        customer, order = self._customer_for_order(user_id, order_id)
        if str(order["status"] or "").lower() in {"cancelled", "completed"}:
            raise ValueError("Payment is not available for this order")
        invoice_id, _ = self.invoices.create_from_order(order_id)
        with self.database.connect() as conn:
            existing = conn.execute("SELECT * FROM payment_transactions WHERE order_id=?", (order_id,)).fetchone()
            if existing and str(existing["status"] or "").lower() not in {"failed", "cancelled"}:
                return self._json(existing)
            payment_id = str(uuid.uuid4())
            amount_cents = int(order["total_cents"] or 0)
            metadata = {"order_id": order_id, "invoice_id": invoice_id, "channel": "customer-web"}
            conn.execute("""INSERT INTO payment_transactions(
                id,order_id,invoice_id,customer_id,amount_cents,currency,provider,status,metadata_json
            ) VALUES(?,?,?,?,?,?,?,?,?)""", (payment_id, order_id, invoice_id, customer["id"], amount_cents, "USD", self.provider.name, "created", json.dumps(metadata, sort_keys=True)))
            conn.commit()
        try:
            result = self.provider.create_checkout(payment_id=payment_id, amount_cents=amount_cents, currency="USD", metadata=metadata)
        except PaymentProviderNotConfigured:
            return {"id": payment_id, "order_id": order_id, "invoice_id": invoice_id, "amount_cents": amount_cents, "currency": "USD", "provider": self.provider.name, "status": "not_configured", "payment_required": amount_cents > 0, "checkout_url": None}
        except PaymentProviderError:
            self._set_status(payment_id, "failed")
            raise
        status = str(result.get("status") or "pending")
        self._update_gateway_fields(payment_id, result, status)
        return self.get(payment_id)

    def handle_webhook(self, payload, signature=None):
        event = self.provider.parse_webhook(payload, signature)
        event_id = event.get("event_id")
        if not event_id:
            raise PaymentProviderError("Webhook event has no id")
        with self.database.connect() as conn:
            if conn.execute("SELECT 1 FROM payment_webhook_events WHERE id=?", (event_id,)).fetchone():
                return {"processed": False, "duplicate": True, "event_id": event_id}
            conn.execute("INSERT INTO payment_webhook_events(id,provider,event_type,payment_id) VALUES(?,?,?,?)", (event_id, self.provider.name, event.get("event_type"), event.get("payment_id") or event.get("provider_payment_id")))
            conn.commit()
        payment_id = event.get("payment_id")
        if payment_id and event.get("status") in self.VALID_STATUSES:
            self._set_status(payment_id, event["status"], provider_payment_id=event.get("provider_payment_id"))
        return {"processed": True, "duplicate": False, "event_id": event_id, "status": event.get("status")}

    def _update_gateway_fields(self, payment_id, result, status):
        with self.database.connect() as conn:
            conn.execute("""UPDATE payment_transactions
                SET provider_payment_id=?,checkout_url=?,status=?,metadata_json=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?""", (result.get("provider_payment_id"), result.get("checkout_url"), status, json.dumps(result.get("metadata") or {}, sort_keys=True), payment_id))
            conn.commit()

    def _set_status(self, payment_id, status, provider_payment_id=None):
        if status not in self.VALID_STATUSES:
            raise ValueError("Unsupported payment status: %s" % status)
        with self.database.connect() as conn:
            if provider_payment_id:
                conn.execute("UPDATE payment_transactions SET status=?,provider_payment_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, provider_payment_id, payment_id))
            else:
                conn.execute("UPDATE payment_transactions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, payment_id))
            conn.commit()

    def get(self, payment_id):
        with self.database.connect() as conn:
            row = conn.execute("SELECT * FROM payment_transactions WHERE id=?", (payment_id,)).fetchone()
        if not row:
            raise KeyError("Payment transaction not found")
        return self._json(row)

    @staticmethod
    def _json(row):
        if row is None:
            return None
        if hasattr(row, "keys"):
            return {str(key): row[key] for key in row.keys()}
        return dict(row)
