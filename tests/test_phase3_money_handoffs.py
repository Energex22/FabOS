"""Phase 3 regression tests: integration secrets in admin settings + money handoffs.

Part A — integration secrets:
- Secret setting values never appear in plaintext in any settings API
  response (FastAPI + WSGI, GET and PUT).
- Non-admin callers cannot read or write admin settings (401/403).
- An empty secret submission keeps the existing stored value.
- ResendEmailProvider reads resend_api_key from settings first, falling back
  to RESEND_API_KEY; the log fallback is used when neither is configured.

Part B — money handoffs:
- POST /api/v1/customer/orders/preview returns the same totals as order
  creation without persisting anything.
- Invoices auto-create when an order is created (idempotent); record_payment
  moves open -> partial -> paid and rejects overpayment.
- Order detail exposes a machine-readable next_step (awaiting_payment /
  ready_for_production / ...).
- Start-production refuses unpaid orders with a clear 409-style error.
- The admin invoice-create and record-payment endpoints exist on both
  transports.
"""
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI
from fabos_core.api import create_app
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.customer_commerce import CustomerCommerceService
from fabos_core.services.customer_notifications import (
    CustomerNotificationService, LoggingEmailProvider, ResendEmailProvider,
    default_email_provider)
from fabos_core.services.invoices import InvoiceService
from fabos_core.services.orders import OrderService
from fabos_core.services.permissions import PermissionService
from fabos_core.services.production import ProductionService
from fabos_core.services.quotes import QuoteService
from fabos_core.services.shop_settings import ShopSettingsService


SECRET_VALUE = "re_SUPERSECRET123"


def _no_resend_env(test_case):
    saved = {key: os.environ.pop(key, None) for key in ("RESEND_API_KEY", "RESEND_FROM_EMAIL")}

    def _restore():
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    test_case.addCleanup(_restore)


class _Db:
    """In-memory-ish sqlite database backed by a temp file (migrated)."""

    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "fabos.sqlite3")
        self.db.initialize()
        migrate(self.db)

    def close(self):
        self.tmp.cleanup()


class _Accounts:
    def __init__(self, customer_id="cust-1"):
        self.customer_id = customer_id

    def get_user(self, user_id):
        return {"id": user_id, "active": 1, "account_type": "customer"}

    def customer_for_user(self, user_id):
        return {"id": self.customer_id, "name": "Test Customer", "email": "t@example.com"}


class _Products:
    def get(self, product_id):
        if product_id != "product-1":
            return None
        return {"id": "product-1", "name": "Widget", "price_cents": 2000,
                "estimated_minutes": 60, "estimated_filament_g": 50.0,
                "material": "PLA", "color": "Black"}

    def is_customer_eligible(self, product_id):
        return product_id == "product-1"

    def variants(self, product_id):
        return []


class _Quotes:
    def __init__(self, db):
        self.db = db
        self.saved = 0

    def save(self, data, items, quote_id=None):
        self.saved += 1
        quote_id = "quote-%d" % self.saved
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents,notes) VALUES(?,?,?,?,?,?)",
                (quote_id, "Q-T%d" % self.saved, data.get("customer_id"), data.get("status"),
                 sum(int(i.get("quantity", 1)) * int(i.get("unit_price_cents", 0)) for i in items),
                 data.get("notes", "")))
            for item in items:
                conn.execute(
                    "INSERT INTO quote_items(id,quote_id,product_id,variant_id,description,quantity,unit_price_cents,material,color,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    ("qi-%s-%d" % (quote_id, self.saved), quote_id, item.get("product_id"),
                     item.get("variant_id"), item.get("description"), item.get("quantity"),
                     item.get("unit_price_cents"), item.get("material", ""), item.get("color", ""),
                     item.get("estimated_minutes", 0), item.get("estimated_filament_g", 0)))
            conn.commit()
        return quote_id


def _shipping():
    return {"address": "1 Main St", "city": "Auxvasse", "state": "MO", "zip": "65231"}


def _seed_settings(shop):
    shop.set_validated("storefront_enabled", "true")
    shop.set_validated("storefront_ordering_enabled", "true")
    shop.set_validated("shipping_mode", "flat")
    shop.set_validated("shipping_flat_cents", "600")
    shop.set_validated("default_tax_percent", "8.25")
    shop.set_validated("default_turnaround_days", "7")
    shop.set_validated("minimum_order_cents", "0")


# ---------------------------------------------------------------------------
# Part A: secret masking + admin gating
# ---------------------------------------------------------------------------

class SecretMaskingTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.shop = ShopSettingsService(self.db.db)

    def test_masked_snapshot_never_contains_secret_plaintext(self):
        self.shop.set_validated("resend_api_key", SECRET_VALUE)
        self.shop.set_validated("stripe_secret_key", "sk_test_abc")
        snapshot = self.shop.masked_snapshot()
        self.assertEqual(snapshot["resend_api_key"], {"configured": True})
        self.assertEqual(snapshot["stripe_secret_key"], {"configured": True})
        # Unset secrets report configured False; non-secrets pass through.
        self.assertEqual(snapshot["square_access_token"], {"configured": False})
        self.assertEqual(snapshot["shop_name"], "WireVault FabOS")
        blob = json.dumps(snapshot)
        self.assertNotIn(SECRET_VALUE, blob)
        self.assertNotIn("sk_test_abc", blob)

    def test_secret_keys_are_advertised(self):
        keys = ShopSettingsService.secret_keys()
        self.assertIn("resend_api_key", keys)
        self.assertIn("stripe_secret_key", keys)
        # Publishable keys are public by design — not secrets.
        self.assertNotIn("stripe_publishable_key", keys)

    def _fastapi_client(self, account_type="administrator", role="owner"):
        core = SimpleNamespace(shop_settings=self.shop)
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "u1", "account_type": account_type, "role": role}
        return TestClient(app)

    def _wsgi_api(self, account_type="administrator"):
        core = SimpleNamespace(
            shop_settings=self.shop,
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": "u1", "account_type": account_type}),
            accounts=SimpleNamespace(get_user=lambda uid: {"id": uid, "role": "owner"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        return FabOSAPI(core), {"Authorization": "Bearer test-token"}

    def test_fastapi_settings_get_masks_secrets(self):
        self.shop.set_validated("resend_api_key", SECRET_VALUE)
        response = self._fastapi_client().get("/api/v1/admin/settings")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["settings"]["resend_api_key"], {"configured": True})
        self.assertIn("resend_api_key", body["secret_keys"])
        self.assertNotIn(SECRET_VALUE, response.text)

    def test_fastapi_settings_put_masks_secret_echo(self):
        response = self._fastapi_client().put(
            "/api/v1/admin/settings", json={"key": "resend_api_key", "value": SECRET_VALUE})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["value"], {"configured": True})
        self.assertNotIn(SECRET_VALUE, response.text)
        # ...but the value really was stored.
        self.assertEqual(self.shop.get("resend_api_key"), SECRET_VALUE)

    def test_fastapi_empty_secret_submission_keeps_existing(self):
        self.shop.set_validated("resend_api_key", SECRET_VALUE)
        response = self._fastapi_client().put(
            "/api/v1/admin/settings", json={"key": "resend_api_key", "value": ""})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json().get("unchanged"))
        self.assertEqual(self.shop.get("resend_api_key"), SECRET_VALUE)

    def test_wsgi_settings_get_and_put_mask_secrets(self):
        self.shop.set_validated("resend_api_key", SECRET_VALUE)
        api, headers = self._wsgi_api()
        result = api.request("GET", "/api/v1/admin/settings", {}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["settings"]["resend_api_key"], {"configured": True})
        self.assertNotIn(SECRET_VALUE, json.dumps(result["data"]))
        result = api.request("PUT", "/api/v1/admin/settings",
                             {"key": "stripe_secret_key", "value": "sk_live_xyz"}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["value"], {"configured": True})
        self.assertNotIn("sk_live_xyz", json.dumps(result["data"]))
        # Empty submission keeps the stored value.
        result = api.request("PUT", "/api/v1/admin/settings",
                             {"key": "stripe_secret_key", "value": ""}, headers)
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["data"].get("unchanged"))
        self.assertEqual(self.shop.get("stripe_secret_key"), "sk_live_xyz")


class SettingsAuthTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.shop = ShopSettingsService(self.db.db)

    def _fastapi_client(self, account_type):
        core = SimpleNamespace(shop_settings=self.shop)
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "u1", "account_type": account_type, "role": "staff"}
        return TestClient(app)

    def _wsgi_api(self, account_type):
        core = SimpleNamespace(
            shop_settings=self.shop,
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": "u1", "account_type": account_type}),
            accounts=SimpleNamespace(get_user=lambda uid: {"id": uid, "role": "staff"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        return FabOSAPI(core), {"Authorization": "Bearer test-token"}

    def test_fastapi_non_admin_cannot_read_or_write_settings(self):
        client = self._fastapi_client("customer")
        self.assertIn(client.get("/api/v1/admin/settings").status_code, (401, 403))
        response = client.put("/api/v1/admin/settings",
                              json={"key": "shop_name", "value": "Hacked"})
        self.assertIn(response.status_code, (401, 403))
        self.assertEqual(self.shop.get("shop_name"), "WireVault FabOS")

    def test_wsgi_non_admin_cannot_read_or_write_settings(self):
        api, headers = self._wsgi_api("employee")
        result = api.request("GET", "/api/v1/admin/settings", {}, headers)
        self.assertIn(result["status"], (401, 403))
        result = api.request("PUT", "/api/v1/admin/settings",
                             {"key": "shop_name", "value": "Hacked"}, headers)
        self.assertIn(result["status"], (401, 403))
        self.assertEqual(self.shop.get("shop_name"), "WireVault FabOS")


class ResendProviderTests(unittest.TestCase):
    def setUp(self):
        _no_resend_env(self)
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.shop = ShopSettingsService(self.db.db)

    def test_settings_key_preferred_over_env(self):
        os.environ["RESEND_API_KEY"] = "re_env_key"
        self.shop.set_validated("resend_api_key", "re_settings_key")
        provider = default_email_provider(self.shop)
        self.assertIsInstance(provider, ResendEmailProvider)
        self.assertEqual(provider.api_key, "re_settings_key")

    def test_env_fallback_when_setting_unset(self):
        os.environ["RESEND_API_KEY"] = "re_env_key"
        provider = default_email_provider(self.shop)
        self.assertIsInstance(provider, ResendEmailProvider)
        self.assertEqual(provider.api_key, "re_env_key")

    def test_log_fallback_when_nothing_configured(self):
        provider = default_email_provider(self.shop)
        self.assertIsInstance(provider, LoggingEmailProvider)

    def test_service_without_settings_still_honors_env(self):
        os.environ["RESEND_API_KEY"] = "re_env_key"
        service = CustomerNotificationService(self.db.db)
        self.assertIsInstance(service.provider, ResendEmailProvider)
        self.assertEqual(service.provider.api_key, "re_env_key")

    def test_from_email_prefers_resend_from_email_setting(self):
        service = CustomerNotificationService(self.db.db, self.shop)
        self.shop.set_validated("resend_from_email", "FABVEX <hello@fabvex.com>")
        self.shop.set_validated("shop_email", "shop@example.com")
        self.assertEqual(service._from_email(), "FABVEX <hello@fabvex.com>")

    def test_from_email_falls_back_through_chain(self):
        service = CustomerNotificationService(self.db.db, self.shop)
        self.shop.set_validated("notification_from_email", "notify@example.com")
        self.shop.set_validated("shop_email", "shop@example.com")
        self.assertEqual(service._from_email(), "notify@example.com")


# ---------------------------------------------------------------------------
# Part B: money handoffs
# ---------------------------------------------------------------------------

class TotalsPreviewTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.shop = ShopSettingsService(self.db.db)
        _seed_settings(self.shop)
        with self.db.db.connect() as conn:
            conn.execute("INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                         ("cust-1", "Test Customer", "t@example.com"))
            conn.execute(
                "INSERT INTO products(id,name,price_cents,estimated_minutes,estimated_filament_g) VALUES(?,?,?,?,?)",
                ("product-1", "Widget", 2000, 60, 50.0))
            conn.commit()
        self.quotes = _Quotes(self.db.db)
        self.service = CustomerCommerceService(
            self.db.db, _Accounts(), _Products(), self.quotes, self.shop)

    def _items(self):
        return [{"productId": "product-1", "quantity": 2}]

    def _counts(self):
        with self.db.db.connect() as conn:
            orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
            quotes = conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0]
        return orders, quotes

    def test_preview_matches_create_order_totals(self):
        preview = self.service.preview_order_totals("user-1", self._items(), _shipping())
        self.assertEqual(preview["subtotal_cents"], 4000)
        self.assertEqual(preview["shipping_cents"], 600)
        self.assertEqual(preview["tax_cents"], 330)
        self.assertEqual(preview["total_cents"], 4930)
        row, _, subtotal, shipping, tax, total = self.service.create_order(
            "user-1", self._items(), _shipping())
        self.assertEqual((subtotal, shipping, tax, total), (4000, 600, 330, 4930))

    def test_preview_persists_nothing(self):
        before = self._counts()
        self.service.preview_order_totals("user-1", self._items(), _shipping())
        self.assertEqual(self._counts(), before)
        self.assertEqual(self.quotes.saved, 0)

    def test_preview_runs_create_order_validations(self):
        with self.assertRaises(ValueError):
            self.service.preview_order_totals("user-1", [], _shipping())
        with self.assertRaises(ValueError):
            self.service.preview_order_totals(
                "user-1", [{"productId": "nope", "quantity": 1}], _shipping())
        with self.assertRaises(ValueError):
            self.service.preview_order_totals("user-1", self._items(), {})


class InvoiceLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.shop = ShopSettingsService(self.db.db)
        _seed_settings(self.shop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.invoices = InvoiceService(self.db.db, Path(self.tmp.name))
        self.quotes = QuoteService(self.db.db)
        self.quotes.invoices = self.invoices
        self.orders = OrderService(self.db.db)
        with self.db.db.connect() as conn:
            conn.execute("INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                         ("cust-1", "Test Customer", "t@example.com"))
            conn.commit()

    def _order_from_quote(self, total_cents=5000):
        with self.db.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("quote-1", "Q-1", "cust-1", "sent", total_cents))
            conn.execute(
                "INSERT INTO quote_items(id,quote_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?)",
                ("qi-1", "quote-1", "Widget", 1, total_cents))
            conn.commit()
        return self.quotes.convert_to_order("quote-1")

    def test_convert_to_order_auto_creates_invoice(self):
        order_id = self._order_from_quote()
        with self.db.db.connect() as conn:
            inv = conn.execute(
                "SELECT * FROM invoices WHERE order_id=? AND status<>'void'", (order_id,)).fetchone()
        self.assertIsNotNone(inv)
        self.assertEqual(inv["status"], "open")
        self.assertEqual(inv["total_cents"], 5000)

    def test_invoice_creation_is_idempotent(self):
        order_id = self._order_from_quote()
        first, created_first = self.invoices.create_from_order(order_id)
        second, created_second = self.invoices.create_from_order(order_id)
        self.assertEqual(first, second)
        self.assertFalse(created_second)

    def test_record_payment_transitions_open_partial_paid(self):
        order_id = self._order_from_quote()
        invoice_id, _ = self.invoices.create_from_order(order_id)
        self.invoices.record_payment(invoice_id, 2000, "Cash")
        with self.db.db.connect() as conn:
            inv = conn.execute("SELECT status,paid_cents FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        self.assertEqual((inv["status"], inv["paid_cents"]), ("partial", 2000))
        self.invoices.record_payment(invoice_id, 3000, "Cash")
        with self.db.db.connect() as conn:
            inv = conn.execute("SELECT status,paid_cents FROM invoices WHERE id=?", (invoice_id,)).fetchone()
        self.assertEqual((inv["status"], inv["paid_cents"]), ("paid", 5000))

    def test_record_payment_rejects_overpayment(self):
        order_id = self._order_from_quote()
        invoice_id, _ = self.invoices.create_from_order(order_id)
        with self.assertRaises(ValueError):
            self.invoices.record_payment(invoice_id, 6000, "Cash")

    def test_zero_value_order_gets_no_invoice(self):
        with self.db.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("quote-0", "Q-0", "cust-1", "sent", 0))
            conn.execute(
                "INSERT INTO quote_items(id,quote_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?)",
                ("qi-0", "quote-0", "Free sample", 1, 0))
            conn.commit()
        order_id = self.quotes.convert_to_order("quote-0")
        with self.db.db.connect() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM invoices WHERE order_id=?", (order_id,)).fetchone()[0]
        self.assertEqual(count, 0)

    def test_next_step_follows_money_first_lifecycle(self):
        order_id = self._order_from_quote()
        step = self.orders.next_step(order_id)
        self.assertEqual(step["step"], "awaiting_payment")
        invoice_id, _ = self.invoices.create_from_order(order_id)
        self.invoices.record_payment(invoice_id, 5000, "Cash")
        step = self.orders.next_step(order_id)
        self.assertEqual(step["step"], "ready_for_production")
        self.assertIn("step", step)
        self.assertIn("label", step)


class StartProductionGateTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.invoices = InvoiceService(self.db.db, Path(self.tmp.name))
        self.production = ProductionService(self.db.db, SimpleNamespace(publish=lambda *a, **k: None))

    def _confirmed_order(self, total_cents=5000):
        with self.db.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,status,total_cents) VALUES(?,?,?,?)",
                ("q-1", "Q-1", "approved", total_cents))
            conn.execute(
                "INSERT INTO quote_items(id,quote_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?)",
                ("qi-1", "q-1", "Widget", 1, total_cents))
            conn.execute(
                "INSERT INTO orders(id,order_number,status,total_cents,quote_id) VALUES(?,?,?,?,?)",
                ("o-1", "O-1", "confirmed", total_cents, "q-1"))
            conn.commit()
        return "o-1"

    def test_unpaid_order_is_rejected_with_clear_reason(self):
        order_id = self._confirmed_order()
        self.invoices.create_from_order(order_id)
        with self.assertRaises(ValueError) as ctx:
            self.production.create_jobs_from_order(order_id)
        message = str(ctx.exception)
        self.assertIn("fully paid", message)
        self.assertIn("$50.00", message)

    def test_fully_paid_order_starts_jobs(self):
        order_id = self._confirmed_order()
        invoice_id, _ = self.invoices.create_from_order(order_id)
        self.invoices.record_payment(invoice_id, 5000, "Cash")
        created = self.production.create_jobs_from_order(order_id)
        self.assertEqual(len(created), 1)

    def test_wsgi_start_production_returns_409_for_unpaid(self):
        order_id = self._confirmed_order()
        self.invoices.create_from_order(order_id)
        core = SimpleNamespace(
            production=self.production,
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": "u1", "account_type": "administrator"}),
            accounts=SimpleNamespace(get_user=lambda uid: {"id": uid, "role": "owner"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        api = FabOSAPI(core)
        headers = {"Authorization": "Bearer test-token"}
        result = api.request("POST", "/api/v1/admin/orders/%s/start-production" % order_id, {}, headers)
        self.assertEqual(result["status"], 409)
        self.assertIn("fully paid", result["data"]["error"])


class MoneyEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.shop = ShopSettingsService(self.db.db)
        _seed_settings(self.shop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        with self.db.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) VALUES(?,?,?,?,?,?)",
                ("admin-1", "admin", "x", "owner", 1, "administrator"))
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) VALUES(?,?,?,?,?,?)",
                ("cust-user-1", "custuser", "x", "customer", 1, "customer"))
            conn.execute("INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                         ("cust-1", "Test Customer", "t@example.com"))
            conn.execute("INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)",
                         ("cust-user-1", "cust-1"))
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("q-1", "Q-1", "cust-1", "sent", 5000))
            conn.execute(
                "INSERT INTO quote_items(id,quote_id,description,quantity,unit_price_cents) VALUES(?,?,?,?,?)",
                ("qi-1", "q-1", "Widget", 1, 5000))
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,status,total_cents,quote_id) VALUES(?,?,?,?,?,?)",
                ("o-1", "O-1", "cust-1", "pending", 5000, "q-1"))
            conn.commit()
        self.accounts = AccountService(self.db.db)
        self.permissions = PermissionService(self.db.db)
        self.invoices = InvoiceService(self.db.db, Path(self.tmp.name), self.accounts, self.permissions)
        self.quotes = QuoteService(self.db.db)
        self.quotes.invoices = self.invoices
        self.orders = OrderService(self.db.db, self.accounts, self.permissions)

    def _fastapi_client(self, account_type="administrator", role="owner"):
        core = SimpleNamespace(
            shop_settings=self.shop,
            invoices=self.invoices,
            permissions=self.permissions,
            orders=self.orders,
            production=SimpleNamespace(),
            customer_commerce=SimpleNamespace(),
        )
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "admin-1", "account_type": account_type, "role": role}
        return TestClient(app)

    def _invoice_id(self):
        invoice_id, _ = self.invoices.create_from_order("o-1")
        return invoice_id

    def test_fastapi_create_invoice_from_order(self):
        client = self._fastapi_client()
        response = client.post("/api/v1/admin/orders/o-1/invoice", json={})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["created"])
        self.assertEqual(body["invoice"]["total_cents"], 5000)
        # Idempotent: second call returns the same invoice, created=False.
        response = client.post("/api/v1/admin/orders/o-1/invoice", json={})
        self.assertFalse(response.json()["created"])
        self.assertEqual(response.json()["invoice_id"], body["invoice_id"])

    def test_fastapi_create_invoice_unknown_order_is_404(self):
        client = self._fastapi_client()
        response = client.post("/api/v1/admin/orders/nope/invoice", json={})
        self.assertEqual(response.status_code, 404)

    def test_fastapi_record_payment(self):
        client = self._fastapi_client()
        invoice_id = self._invoice_id()
        response = client.post("/api/v1/admin/invoices/%s/payments" % invoice_id,
                               json={"amount_cents": 2000, "method": "Cash"})
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["recorded_cents"], 2000)
        self.assertEqual(body["invoice"]["status"], "partial")
        response = client.post("/api/v1/admin/invoices/%s/payments" % invoice_id,
                               json={"amount_cents": 3000, "method": "Cash"})
        self.assertEqual(response.json()["invoice"]["status"], "paid")

    def test_fastapi_record_payment_rejects_overpayment(self):
        client = self._fastapi_client()
        invoice_id = self._invoice_id()
        response = client.post("/api/v1/admin/invoices/%s/payments" % invoice_id,
                               json={"amount_cents": 999999, "method": "Cash"})
        self.assertEqual(response.status_code, 400)

    def test_fastapi_customer_cannot_create_invoice_or_record_payment(self):
        client = self._fastapi_client(account_type="customer", role="customer")
        response = client.post("/api/v1/admin/orders/o-1/invoice", json={})
        self.assertIn(response.status_code, (401, 403))
        response = client.post("/api/v1/admin/invoices/%s/payments" % self._invoice_id(),
                               json={"amount_cents": 100, "method": "Cash"})
        self.assertIn(response.status_code, (401, 403))

    def _wsgi_api(self, account_type="administrator"):
        user_id = "cust-user-1" if account_type == "customer" else "admin-1"
        core = SimpleNamespace(
            invoices=self.invoices,
            orders=self.orders,
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": user_id, "account_type": account_type}),
            accounts=self.accounts,
            permissions=self.permissions,
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        return FabOSAPI(core), {"Authorization": "Bearer test-token"}

    def test_wsgi_create_invoice_and_record_payment(self):
        api, headers = self._wsgi_api()
        result = api.request("POST", "/api/v1/admin/orders/o-1/invoice", {}, headers)
        self.assertEqual(result["status"], 200)
        self.assertTrue(result["data"]["created"])
        invoice_id = result["data"]["invoice_id"]
        result = api.request("POST", "/api/v1/admin/invoices/%s/payments" % invoice_id,
                             {"amount_cents": 5000, "method": "Cash"}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["invoice"]["status"], "paid")

    def test_wsgi_customer_cannot_record_payment(self):
        api, headers = self._wsgi_api(account_type="customer")
        result = api.request("POST", "/api/v1/admin/invoices/%s/payments" % self._invoice_id(),
                             {"amount_cents": 100, "method": "Cash"}, headers)
        self.assertIn(result["status"], (401, 403))

    def test_fastapi_admin_order_detail(self):
        client = self._fastapi_client()
        self._invoice_id()
        response = client.get("/api/v1/admin/orders/o-1")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["order"]["id"], "o-1")
        self.assertEqual(body["next_step"]["step"], "awaiting_payment")
        self.assertEqual(body["invoice_id"], body["invoice"]["id"])
        self.assertEqual(body["invoice"]["total_cents"], 5000)

    def test_fastapi_admin_order_detail_unknown_order_is_404(self):
        client = self._fastapi_client()
        response = client.get("/api/v1/admin/orders/nope")
        self.assertEqual(response.status_code, 404)

    def test_fastapi_customer_cannot_read_admin_order_detail(self):
        client = self._fastapi_client(account_type="customer", role="customer")
        response = client.get("/api/v1/admin/orders/o-1")
        self.assertIn(response.status_code, (401, 403))

    def test_wsgi_admin_order_detail(self):
        api, headers = self._wsgi_api()
        self._invoice_id()
        result = api.request("GET", "/api/v1/admin/orders/o-1", {}, headers)
        self.assertEqual(result["status"], 200)
        body = result["data"]
        self.assertEqual(body["order"]["id"], "o-1")
        self.assertEqual(body["next_step"]["step"], "awaiting_payment")
        self.assertEqual(body["invoice_id"], (body["invoice"] or {}).get("id"))

    def test_wsgi_admin_order_detail_unknown_order_is_404(self):
        api, headers = self._wsgi_api()
        result = api.request("GET", "/api/v1/admin/orders/nope", {}, headers)
        self.assertEqual(result["status"], 404)

    def test_wsgi_customer_cannot_read_admin_order_detail(self):
        api, headers = self._wsgi_api(account_type="customer")
        result = api.request("GET", "/api/v1/admin/orders/o-1", {}, headers)
        self.assertIn(result["status"], (401, 403))


class PreviewEndpointTests(unittest.TestCase):
    def setUp(self):
        self.db = _Db()
        self.addCleanup(self.db.close)
        self.shop = ShopSettingsService(self.db.db)
        _seed_settings(self.shop)
        self.commerce = CustomerCommerceService(
            self.db.db, _Accounts(), _Products(), _Quotes(self.db.db), self.shop)

    def _payload(self):
        return {
            "items": [{"productId": "product-1", "quantity": 2}],
            "shippingAddress": _shipping(),
            "notes": "",
        }

    def test_fastapi_preview_endpoint(self):
        core = SimpleNamespace(customer_commerce=self.commerce)
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "user-1", "account_type": "customer", "role": "customer"}
        client = TestClient(app)
        response = client.post("/api/v1/customer/orders/preview", json=self._payload())
        self.assertEqual(response.status_code, 200)
        totals = response.json()["totals"]
        self.assertEqual(totals["subtotal"], 40.00)
        self.assertEqual(totals["shipping"], 6.00)
        self.assertEqual(totals["tax"], 3.30)
        self.assertEqual(totals["total"], 49.30)

    def test_fastapi_preview_rejects_bad_input(self):
        core = SimpleNamespace(customer_commerce=self.commerce)
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "user-1", "account_type": "customer", "role": "customer"}
        client = TestClient(app)
        payload = self._payload()
        payload["items"] = [{"productId": "nope", "quantity": 1}]
        response = client.post("/api/v1/customer/orders/preview", json=payload)
        self.assertEqual(response.status_code, 400)

    def test_wsgi_preview_endpoint(self):
        core = SimpleNamespace(
            customer_commerce=self.commerce,
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": "user-1", "account_type": "customer"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        api = FabOSAPI(core)
        result = api.request("POST", "/api/v1/customer/orders/preview", self._payload(),
                             {"Authorization": "Bearer test-token"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["totals"]["total"], 49.30)


if __name__ == "__main__":
    unittest.main()
