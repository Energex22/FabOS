"""Provider-neutral customer payment orchestration.

The storefront talks to this service instead of knowing whether FabOS eventually
uses Stripe, Square, or another gateway.  The default provider is intentionally
unconfigured: creating an order never pretends that a payment was collected.
"""
import json
import os
import uuid
from datetime import datetime, timezone


class PaymentProviderNotConfigured(RuntimeError):
    pass


class PaymentProvider:
    name = "base"

    def create_checkout(self, *, payment_id, amount_cents, currency, metadata):
        raise NotImplementedError


class UnconfiguredPaymentProvider(PaymentProvider):
    name = "unconfigured"

    def create_checkout(self, *, payment_id, amount_cents, currency, metadata):
        raise PaymentProviderNotConfigured("No payment provider is configured")


class PaymentService:
    """Persist payment attempts and delegate gateway work to a provider adapter."""

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
            conn.commit()

    def _build_provider(self):
        name = os.environ.get("FABOS_PAYMENT_PROVIDER", "none").strip().lower()
        # Gateway adapters are deliberately not selected until credentials and
        # provider-specific behavior are supplied.  Both future adapters use
        # this same PaymentProvider seam.
        if name in ("", "none", "unconfigured"):
            return UnconfiguredPaymentProvider()
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
            ) VALUES(?,?,?,?,?,?,?,?,?)""", (
                payment_id, order_id, invoice_id, customer["id"], amount_cents, "USD",
                self.provider.name, "created", json.dumps(metadata, sort_keys=True)
            ))
            conn.commit()

        try:
            result = self.provider.create_checkout(
                payment_id=payment_id,
                amount_cents=amount_cents,
                currency="USD",
                metadata=metadata,
            )
        except PaymentProviderNotConfigured:
            return {
                "id": payment_id,
                "order_id": order_id,
                "invoice_id": invoice_id,
                "amount_cents": amount_cents,
                "currency": "USD",
                "provider": self.provider.name,
                "status": "not_configured",
                "payment_required": amount_cents > 0,
                "checkout_url": None,
            }

        status = str(result.get("status") or "pending")
        with self.database.connect() as conn:
            conn.execute("""UPDATE payment_transactions
                SET provider_payment_id=?,checkout_url=?,status=?,metadata_json=?,updated_at=CURRENT_TIMESTAMP
                WHERE id=?""", (
                result.get("provider_payment_id"), result.get("checkout_url"), status,
                json.dumps(result.get("metadata") or metadata, sort_keys=True), payment_id
            ))
            conn.commit()
        return self.get(payment_id)

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
