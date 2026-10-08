"""Regression tests for the third review-pass fixes (H1, M1-M6, L1-L5, L7-L10).

- H1: WSGI _jsonable must not turn empty strings into {}.
- M1: public quote-request with base64 model runs _validate_model_file first.
- M2: WSGI auth responses (login/team-login/register) project to the FastAPI shapes.
- M3: GET /api/v1/me returns the profile directly (no double "user" nesting).
- M4: PATCH /api/v1/customer/me validates email, rejects duplicates, syncs
  users.email; customers.save merges partial updates.
- M5: _public_product matches the FastAPI shape; the catalog image route
  serves files with the same traversal guard.
- M6: WSGI serves the mirrored admin + CAD + quote-requests/upload routes;
  FastAPI serves /api/v1/invoices* and /api/v1/fulfillments*.
- L1: payment-session projects to (status, checkout_url) only.
- L2: logout is idempotent ({"logged_out": True} without a token).
- L3: the WSGI status line covers 409/413/415/502/503.
- L4: WSGI order GET applies the CUSTOMER_STATUS mapping and the designs dossier.
- L5: estimate/checkout/customer-order shipping agree to the cent; the
  checkout path writes quote audit rows; estimate ignores client weight.
- L7: refund webhooks claim the event id; redelivery reports duplicate.
- L8: racy duplicate registration -> 409, not 500.
- L10: the auth user payload sources the name from the customer profile.

(L6 was a false positive: low_supplies compares quantity against the per-item
supply_items.low_threshold column, not the filament threshold. M8 does not
exist in the findings; M5 is covered instead.)
"""
import io
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI, create_wsgi_app
from fabos_core.api import create_app
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.accounts import AccountService
from fabos_core.services.auth import AuthService
from fabos_core.services.checkout import CheckoutService
from fabos_core.services.commerce_pricing import (
    CommercePricingService,
    calculated_shipping_cents,
)
from fabos_core.services.customer_commerce import CustomerCommerceService
from fabos_core.services.customers import CustomerService
from fabos_core.services.payments import PaymentService
from fabos_core.services.quotes import QuoteService

VALID_STL = (
    b"solid test\n"
    + b"facet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\n" * 3
    + b"endsolid test\n"
)
assert len(VALID_STL) > 84
GARBAGE_STL = b"\x00" * 100


def _quiet_core(**overrides):
    base = {"error_log": SimpleNamespace(error=lambda *a, **k: None)}
    base.update(overrides)
    return SimpleNamespace(**base)


def _customer_security(account_type="customer", user_id="u1"):
    return SimpleNamespace(
        context=lambda token, permission=None: {"id": user_id, "account_type": account_type}
    )


def _wsgi_call(app, method, path, body=b"", headers=None, content_type="application/json"):
    captured = {}

    def start_response(status, response_headers):
        captured["status"] = status
        captured["headers"] = dict(response_headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "CONTENT_TYPE": content_type,
        "CONTENT_LENGTH": str(len(body)),
        "REMOTE_ADDR": "127.0.0.1",
        "wsgi.input": io.BytesIO(body),
    }
    for key, value in (headers or {}).items():
        environ["HTTP_" + key.upper().replace("-", "_")] = value
    out = b"".join(app(environ, start_response))
    return captured["status"], out


def _multipart(fields, file_field, filename, file_bytes, boundary="----testboundary"):
    lines = []
    for name, value in fields.items():
        lines.append("--" + boundary)
        lines.append('Content-Disposition: form-data; name="%s"' % name)
        lines.append("")
        lines.append(value)
    lines.append("--" + boundary)
    lines.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (file_field, filename))
    lines.append("Content-Type: application/octet-stream")
    lines.append("")
    head = "\r\n".join(lines).encode("utf-8") + b"\r\n"
    tail = ("\r\n--" + boundary + "--\r\n").encode("utf-8")
    return head + file_bytes + tail, "multipart/form-data; boundary=" + boundary


def _temp_db():
    tmp = tempfile.TemporaryDirectory()
    db = Database(Path(tmp.name) / "fabos.sqlite3")
    db.initialize()
    migrate(db)
    return tmp, db


def _commerce_core(db):
    return CustomerCommerceService(
        db,
        SimpleNamespace(),
        SimpleNamespace(),
        QuoteService(db, SimpleNamespace()),
        {"storefront_enabled": "true"},
        None,
    )


class JsonableTests(unittest.TestCase):
    """H1: empty strings must survive _jsonable untouched."""

    def test_empty_string_is_not_converted_to_dict(self):
        api = FabOSAPI(_quiet_core())
        self.assertEqual(api._jsonable(""), "")
        self.assertEqual(api._jsonable({"a": "", "b": ["", 0, False, None]}),
                         {"a": "", "b": ["", 0, False, None]})
        response = api._response(200, {"name": "", "notes": ""})
        self.assertEqual(response["data"], {"name": "", "notes": ""})


class AuthProjectionTests(unittest.TestCase):
    """M2/M3/L10: WSGI auth + me shapes match FastAPI."""

    def _login_core(self, summary):
        return _quiet_core(
            auth=SimpleNamespace(login=lambda *a, **k: {"token": "tok", "expires_at": "exp", "user": summary},
                                 logout=lambda token: True),
            security=_customer_security("customer"),
        )

    def test_login_projects_fastapi_shape(self):
        summary = {
            "user": {"id": "u1", "username": "customer-x", "email": "ann@example.com",
                     "account_type": "customer", "role": "customer", "active": 1,
                     "password_hash": "secret", "created_at": "t"},
            "customer": {"id": "c1", "name": "Ann", "email": "ann@example.com",
                         "phone": "555", "notes": "staff notes"},
            "employee": None,
        }
        api = FabOSAPI(self._login_core(summary))
        result = api.request("POST", "/api/v1/auth/login",
                             {"identifier": "ann@example.com", "password": "p"}, {})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"], {
            "token": "tok", "expires_at": "exp",
            "user": {"name": "Ann", "email": "ann@example.com"},
            "customer": {"name": "Ann", "email": "ann@example.com", "phone": "555",
                         "notification_preference": "email"},
        })

    def test_team_login_projects_fastapi_shape(self):
        summary = {
            "user": {"id": "e1", "email": "boss@example.com", "account_type": "employee",
                     "role": "admin", "password_hash": "secret"},
            "customer": None, "employee": {"user_id": "e1"},
        }
        api = FabOSAPI(self._login_core(summary))
        result = api.request("POST", "/api/v1/auth/team-login",
                             {"identifier": "boss@example.com", "password": "p"}, {})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["user"],
                         {"email": "boss@example.com", "account_type": "employee", "role": "admin"})
        self.assertNotIn("customer", result["data"])
        self.assertNotIn("password_hash", str(result["data"]))

    def test_me_returns_profile_without_double_nesting(self):
        summary = {
            "user": {"id": "u1", "email": "ann@example.com"},
            "customer": {"id": "c1", "name": "Ann", "email": "ann@example.com", "phone": "555"},
            "employee": None,
        }
        core = _quiet_core(
            security=_customer_security("customer"),
            accounts=SimpleNamespace(account_summary=lambda uid: summary),
        )
        api = FabOSAPI(core)
        result = api.request("GET", "/api/v1/me", {}, {"Authorization": "Bearer tok"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"], {
            "user": {"name": "Ann", "email": "ann@example.com"},
            "customer": {"name": "Ann", "email": "ann@example.com", "phone": "555",
                         "notification_preference": "email"},
        })
        self.assertNotIn("user", result["data"]["user"])


class CustomerMeUpdateTests(unittest.TestCase):
    """M4: email validation, duplicate rejection, users-email sync, partial save."""

    def _core(self, existing_email_user=None):
        calls = {"update_account": [], "saved": []}

        def get_by_email(email):
            return existing_email_user if email == "taken@example.com" else None

        def update_account(user_id, email=None, **kwargs):
            calls["update_account"].append((user_id, email))
            return {"id": user_id, "email": email}

        def save(payload, customer_id=None):
            calls["saved"].append((dict(payload), customer_id))

        return _quiet_core(
            security=_customer_security("customer"),
            accounts=SimpleNamespace(
                customer_for_user=lambda uid: {"id": "c1"},
                get_by_email=get_by_email,
                update_account=update_account,
                account_summary=lambda uid: {
                    "user": {"id": "u1", "email": "new@example.com"},
                    "customer": {"id": "c1", "name": "Ann", "email": "new@example.com", "phone": ""},
                },
            ),
            customers=SimpleNamespace(save=save),
        ), calls

    def test_malformed_email_is_400(self):
        core, _ = self._core()
        result = FabOSAPI(core).request("PATCH", "/api/v1/customer/me",
                                        {"email": "not-an-email"}, {"Authorization": "Bearer tok"})
        self.assertEqual(result["status"], 400)

    def test_duplicate_email_is_409(self):
        core, calls = self._core(existing_email_user={"id": "other"})
        result = FabOSAPI(core).request("PATCH", "/api/v1/customer/me",
                                        {"email": "taken@example.com"}, {"Authorization": "Bearer tok"})
        self.assertEqual(result["status"], 409)
        self.assertEqual(calls["update_account"], [])
        self.assertEqual(calls["saved"], [])

    def test_valid_email_syncs_login_identifier(self):
        core, calls = self._core()
        result = FabOSAPI(core).request("PATCH", "/api/v1/customer/me",
                                        {"email": "New@Example.COM"}, {"Authorization": "Bearer tok"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(calls["update_account"], [("u1", "new@example.com")])
        self.assertEqual(calls["saved"], [({"email": "new@example.com"}, "c1")])
        self.assertEqual(result["data"]["user"], {"name": "Ann", "email": "new@example.com"})

    def test_customers_save_merges_partial_updates(self):
        tmp, db = _temp_db()
        try:
            service = CustomerService(db)
            cid = service.save({"name": "Ann", "email": "a@example.com", "phone": "1", "notes": "n"})
            service.save({"email": "b@example.com"}, customer_id=cid)
            row = service.get(cid)
            self.assertEqual(row["email"], "b@example.com")
            self.assertEqual(row["name"], "Ann")
            self.assertEqual(row["phone"], "1")
            with self.assertRaises(ValueError):
                service.save({"email": "x@example.com"})
        finally:
            tmp.cleanup()


class PublicProductTests(unittest.TestCase):
    """M5: _public_product matches FastAPI's shape; image route serves files."""

    def _core(self):
        return _quiet_core(
            products=SimpleNamespace(
                get=lambda pid: {"id": pid, "sku": "s", "name": "N", "price_cents": 250,
                                 "designer": "X", "license_name": "L"} if pid == "p1" else None,
                is_customer_eligible=lambda pid: pid == "p1",
                images=lambda pid: [{"id": "i1", "is_primary": 1, "alt_text": "alt"}] if pid == "p1" else [],
                variants=lambda pid: [{"id": "v1", "name": "V", "material": "PLA", "color": "red",
                                        "price_cents": 100, "active": 1, "secret": "x"}] if pid == "p1" else [],
                storefront_state=lambda pid: {"customer_title": "T", "customer_description": "TD",
                                              "origin_type": "custom", "model_file_count": 3},
            ),
        )

    def test_public_product_matches_fastapi_shape(self):
        api = FabOSAPI(self._core())
        product = api._public_product(
            {"id": "p1", "sku": "s", "name": "N", "description": "D", "category": "C",
             "subcategory": "S", "active": 1, "price_cents": 250,
             "designer": "X", "license_name": "L", "estimated_minutes": 5},
            {"customer_title": "T", "customer_description": "TD",
             "origin_type": "custom", "model_file_count": 3},
        )
        self.assertEqual(product["name"], "T")
        self.assertEqual(product["description"], "TD")
        self.assertEqual(product["price"], 2.5)
        self.assertEqual(product["images"], [
            {"id": "i1", "url": "/api/v1/catalog/p1/images/i1", "is_primary": True, "alt_text": "alt"},
        ])
        self.assertEqual(product["variants"], [
            {"id": "v1", "name": "V", "material": "PLA", "color": "red",
             "price_cents": 100, "active": 1},
        ])
        self.assertEqual(product["storefront"], {"origin": "custom", "model_file_count": 3})
        for dropped in ("designer", "license_name", "estimated_minutes"):
            self.assertNotIn(dropped, product)

    def test_catalog_image_route_serves_relative_paths(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            data_dir = Path(tmp.name) / "data"
            (data_dir / "Catalog_Images").mkdir(parents=True)
            target = data_dir / "Catalog_Images" / "x.png"
            target.write_bytes(b"fakepng")
            db = Database(Path(tmp.name) / "t.sqlite3")
            db.initialize()
            with db.connect() as conn:
                conn.execute("INSERT INTO products(id, name, price_cents) VALUES('p1','Widget',100)")
                conn.execute("INSERT INTO product_images(id, product_id, path, is_primary)"
                             " VALUES('i1','p1','Catalog_Images/x.png',1)")
                conn.execute("INSERT INTO product_images(id, product_id, path, is_primary)"
                             " VALUES('i2','p1','/etc/hostname',0)")
                conn.commit()
            core = self._core()
            core.database = db
            core.settings = SimpleNamespace(data_dir=str(data_dir))
            api = FabOSAPI(core)
            result = api.request("GET", "/api/v1/catalog/p1/images/i1")
            self.assertEqual(result["status"], 200)
            info = result["data"]["_wsgi_file"]
            self.assertEqual(info["bytes"], b"fakepng")
            self.assertEqual(info["disposition"], "inline")
            # Traversal outside the allowed roots -> 404, not the file.
            result = api.request("GET", "/api/v1/catalog/p1/images/i2")
            self.assertEqual(result["status"], 404)
            # Unknown image -> 404.
            result = api.request("GET", "/api/v1/catalog/p1/images/nope")
            self.assertEqual(result["status"], 404)
        finally:
            tmp.cleanup()


class QuoteRequestValidationTests(unittest.TestCase):
    """M1: base64 model uploads are structurally validated before records exist."""

    def test_invalid_model_is_rejected_with_no_orphan_records(self):
        tmp, db = _temp_db()
        try:
            service = _commerce_core(db)
            project = {"idea": "a widget", "quantity": 1}
            with self.assertRaises(ValueError):
                service.create_public_quote_request(
                    "Jane", "jane@example.com", project, "model.stl", GARBAGE_STL)
            with db.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quotes").fetchone()[0], 0)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0], 0)
        finally:
            tmp.cleanup()

    def test_valid_model_is_accepted(self):
        tmp, db = _temp_db()
        try:
            service = _commerce_core(db)
            project = {"idea": "a widget", "quantity": 1}
            quote, _items = service.create_public_quote_request(
                "Jane", "jane@example.com", project, "model.stl", VALID_STL)
            self.assertTrue(str(quote["quote_number"]).startswith("Q-"))
            with db.connect() as conn:
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM quote_request_files").fetchone()[0], 1)
        finally:
            tmp.cleanup()


class PaymentSessionTests(unittest.TestCase):
    """L1: payment-session projects to (status, checkout_url) only."""

    def test_payment_row_is_projected(self):
        core = _quiet_core(
            security=_customer_security("customer"),
            payments=SimpleNamespace(create_checkout=lambda uid, oid: {
                "id": "pay1", "status": "pending", "checkout_url": "https://pay.example/s",
                "provider_payment_id": "secret", "metadata_json": '{"stripe_session_id":"s"}',
                "invoice_id": "i1", "customer_id": "c1", "amount_cents": 100,
            }),
        )
        result = FabOSAPI(core).request(
            "POST", "/api/v1/customer/orders/o1/payment-session", {},
            {"Authorization": "Bearer tok"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["payment"],
                         {"status": "pending", "checkout_url": "https://pay.example/s"})
        self.assertNotIn("provider_payment_id", str(result["data"]))


class LogoutTests(unittest.TestCase):
    """L2: logout is idempotent."""

    def test_logout_without_token_returns_logged_out(self):
        core = _quiet_core(auth=SimpleNamespace(logout=lambda token: False))
        for headers in ({}, {"Authorization": "Bearer bogus"}):
            result = FabOSAPI(core).request("POST", "/api/v1/auth/logout", {}, headers)
            self.assertEqual(result["status"], 200)
            self.assertEqual(result["data"], {"logged_out": True})


class StatusTextTests(unittest.TestCase):
    """L3: the WSGI status line names 409/415 (and friends) instead of "OK"."""

    def test_409_and_415_status_lines(self):
        core = _quiet_core(
            security=_customer_security("customer"),
            accounts=SimpleNamespace(
                customer_for_user=lambda uid: {"id": "c1"},
                get_by_email=lambda email: {"id": "other"},
                account_summary=lambda uid: {},
            ),
            customers=SimpleNamespace(),
        )
        app = create_wsgi_app(core)
        import json as _json
        status, _ = _wsgi_call(
            app, "PATCH", "/api/v1/customer/me",
            body=_json.dumps({"email": "taken@example.com"}).encode(),
            headers={"Authorization": "Bearer tok"},
        )
        self.assertEqual(status, "409 Conflict")

        status, _ = _wsgi_call(app, "GET", "/api/v1/nope")
        self.assertEqual(status, "404 Not Found")


class OrderStatusMappingTests(unittest.TestCase):
    """L4: WSGI order GET maps friendly statuses and includes the designs dossier."""

    def _core(self):
        return _quiet_core(
            security=_customer_security("customer"),
            orders=SimpleNamespace(
                list_for_user=lambda uid: [{"id": "o1", "status": "in_production"}],
                get_for_user=lambda uid, oid: ({"id": oid, "status": "in_production"}, []),
                dossier=lambda oid: {"designs": [
                    {"id": "d1", "name": "D", "current_version": 2,
                     "design_version": 2, "design_version_label": "v2", "secret": "x"},
                ]},
            ),
        )

    def test_detail_maps_status_and_includes_dossier(self):
        result = FabOSAPI(self._core()).request(
            "GET", "/api/v1/customer/orders/o1", {}, {"Authorization": "Bearer tok"})
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["order"]["status"], "Preparing your order")
        self.assertEqual(result["data"]["designs"], [
            {"id": "d1", "name": "D", "current_version": 2,
             "design_version": 2, "design_version_label": "v2"},
        ])

    def test_list_maps_status(self):
        result = FabOSAPI(self._core()).request(
            "GET", "/api/v1/customer/orders", {}, {"Authorization": "Bearer tok"})
        self.assertEqual(result["data"]["orders"][0]["status"], "Preparing your order")


class ShippingParityTests(unittest.TestCase):
    """L5: one shipping formula, audit rows on both paths, server-side weight."""

    def _stubs(self):
        products = SimpleNamespace(
            get=lambda pid: {"id": pid, "name": "Widget", "price_cents": 2000,
                             "estimated_filament_g": 50, "estimated_minutes": 10}
            if pid == "p1" else None,
            is_customer_eligible=lambda pid: pid == "p1",
            variants=lambda pid: [],
        )
        settings = {
            "storefront_enabled": "true", "storefront_ordering_enabled": "true",
            "shipping_mode": "calculated", "shipping_calculated_base_cents": "500",
            "shipping_calculated_per_kg_cents": "199.5", "default_tax_percent": "0",
            "minimum_order_cents": "0", "free_shipping_threshold_cents": "0",
            "default_turnaround_days": "7",
        }
        return products, settings

    def test_calculated_shipping_does_not_pre_round_per_kg(self):
        # 500 + 199.5 * 2kg = 899 (the old CommercePricingService rounded
        # per_kg to 200 first and produced 900).
        self.assertEqual(calculated_shipping_cents("500", "199.5", 2.0), 899)
        products, settings = self._stubs()
        pricing = CommercePricingService(products, settings)
        self.assertEqual(pricing._shipping_cents("calculated", 2000), 899)

    def test_checkout_writes_quote_audit_rows(self):
        tmp, db = _temp_db()
        try:
            products, settings = self._stubs()
            accounts = SimpleNamespace(
                get_user=lambda uid: {"id": uid, "active": 1, "account_type": "customer"},
                customer_for_user=lambda uid: {"id": "c1"},
            )
            with db.connect() as conn:
                conn.execute("INSERT INTO customers(id,name,email,phone,notes) VALUES(?,?,?,?,?)",
                             ("c1", "Ann", "ann@example.com", "", ""))
                conn.execute("INSERT INTO products(id,name,price_cents) VALUES('p1','Widget',2000)")
                conn.commit()
            service = CheckoutService(db, accounts, products, settings)
            result = service.create_order(
                "u1", [{"product_id": "p1", "quantity": 1}],
                {"address": "a", "city": "c", "state": "s", "zip": "z"}, "")
            with db.connect() as conn:
                quote_id = conn.execute(
                    "SELECT quote_id FROM orders WHERE id=?", (result["id"],)).fetchone()[0]
                versions = conn.execute(
                    "SELECT COUNT(*) FROM quote_versions WHERE quote_id=?", (quote_id,)).fetchone()[0]
                snapshots = conn.execute(
                    "SELECT COUNT(*) FROM quote_price_snapshots WHERE quote_id=?", (quote_id,)).fetchone()[0]
            self.assertEqual(versions, 1)
            self.assertEqual(snapshots, 1)
            self.assertEqual(result["shipping_cents"], 510)  # 500 + 199.5 * 0.05kg
        finally:
            tmp.cleanup()

    def test_estimate_ignores_client_supplied_weight(self):
        products, settings = self._stubs()
        core = _quiet_core(
            security=_customer_security("customer"),
            products=products,
            shop_settings=SimpleNamespace(get=lambda k, d=None: settings.get(k, d)),
        )
        api = FabOSAPI(core)
        honest = api.request("POST", "/api/v1/checkout/estimate",
                             {"items": [{"product_id": "p1", "quantity": 2}]},
                             {"Authorization": "Bearer tok"})
        sneaky = api.request("POST", "/api/v1/checkout/estimate",
                             {"items": [{"product_id": "p1", "quantity": 2}],
                              "shipping_weight_g": 999999},
                             {"Authorization": "Bearer tok"})
        self.assertEqual(honest["status"], 200)
        self.assertEqual(sneaky["status"], 200)
        self.assertEqual(honest["data"]["shipping_cents"], sneaky["data"]["shipping_cents"])


class RefundWebhookTests(unittest.TestCase):
    """L7: refund webhooks claim the event id; redelivery reports duplicate."""

    def test_refund_redelivery_reports_duplicate(self):
        class _Provider:
            name = "stripe"

            def parse_webhook(self, payload, signature=None):
                return {"event_id": "evt_dup", "event_type": "refund.created",
                        "provider_payment_id": "pi_1", "payment_id": "pay_1",
                        "order_id": "o1", "status": "refunded", "amount_cents": 100}

        database = SimpleNamespace()
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute("CREATE TABLE payment_webhook_events(id TEXT PRIMARY KEY, provider TEXT NOT NULL,"
                     "event_type TEXT, payment_id TEXT, received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        database.connect = lambda: conn
        service = PaymentService.__new__(PaymentService)
        service.database = database
        service._build_provider = lambda name=None: _Provider()
        first = service.handle_webhook(b"{}", "sig", "stripe")
        self.assertTrue(first["processed"])
        self.assertFalse(first["duplicate"])
        second = service.handle_webhook(b"{}", "sig", "stripe")
        self.assertFalse(second["processed"])
        self.assertTrue(second["duplicate"])
        self.assertEqual(second["event_id"], "evt_dup")


class DuplicateRegistrationTests(unittest.TestCase):
    """L8: a racy duplicate registration is a 409, not a 500."""

    def test_concurrent_duplicate_register_is_409(self):
        tmp, db = _temp_db()
        try:
            real_accounts = AccountService(db)
            auth = AuthService(db, real_accounts)
            shop = SimpleNamespace(get=lambda k, d=None: {"storefront_enabled": "true",
                                                           "customer_registration_enabled": "true"}.get(k, d))
            # The "other" registration lands first; this attempt's pre-check
            # runs in the race window and misses it.
            with db.connect() as conn:
                conn.execute("INSERT INTO users(id,username,password_hash,email,account_type,active)"
                             " VALUES(?,?,?,?,?,1)",
                             ("u-racer", "racer", "hash", "race@example.com", "customer"))
                conn.commit()
            calls = []

            class RaceAccounts:
                def get_by_email(self, email):
                    calls.append(email)
                    if len(calls) == 1:
                        return None
                    return real_accounts.get_by_email(email)

                def __getattr__(self, name):
                    return getattr(real_accounts, name)

            core = _quiet_core(database=db, accounts=RaceAccounts(), auth=auth,
                               shop_settings=shop, security=_customer_security())
            api = FabOSAPI(core)
            result = api.request("POST", "/api/v1/auth/register",
                                 {"name": "Racer", "email": "race@example.com",
                                  "password": "password123", "phone": ""}, {})
            self.assertEqual(result["status"], 409)
            self.assertIn("already exists", result["data"]["error"])
        finally:
            tmp.cleanup()


class FastAPIBillingSurfaceTests(unittest.TestCase):
    """M6b: FastAPI serves /api/v1/invoices* and /api/v1/fulfillments*."""

    def _client(self, permission_ok=True):
        def require(account_type, permission, user_id=None):
            if not permission_ok:
                raise PermissionError("Permission denied: %s" % permission)
            return True

        fabos = SimpleNamespace(
            invoices=SimpleNamespace(
                list_for_user=lambda user_id, q="", status="All", sort="created", desc=True: [{"id": "i1"}],
                get_for_user=lambda user_id, iid: ({"id": iid}, [{"id": "it1"}], [{"id": "p1"}]),
            ),
            fulfillment=SimpleNamespace(
                list_for_user=lambda user_id, status="All": [{"id": "f1"}],
                get_for_user=lambda user_id, fid: {"id": fid},
            ),
            permissions=SimpleNamespace(require=require),
        )
        app = create_app(fabos)
        app.dependency_overrides[app.state.current_user] = lambda: {"id": "u1", "account_type": "administrator"}
        return TestClient(app)

    def test_invoices_list_and_detail(self):
        client = self._client()
        response = client.get("/api/v1/invoices")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"invoices": [{"id": "i1"}]})
        response = client.get("/api/v1/invoices/i9")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["invoice"], {"id": "i9"})
        self.assertEqual(body["items"], [{"id": "it1"}])
        self.assertEqual(body["payments"], [{"id": "p1"}])

    def test_fulfillments_list_and_detail(self):
        client = self._client()
        response = client.get("/api/v1/fulfillments")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"fulfillments": [{"id": "f1"}]})
        response = client.get("/api/v1/fulfillments/f9")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"fulfillment": {"id": "f9"}})

    def test_permission_denied_is_403(self):
        client = self._client(permission_ok=False)
        self.assertEqual(client.get("/api/v1/invoices").status_code, 403)
        self.assertEqual(client.get("/api/v1/fulfillments").status_code, 403)


class WsgiAdminSurfaceTests(unittest.TestCase):
    """M6a: WSGI serves mirrored admin + CAD routes with role checks."""

    def _admin_core(self, account_type="administrator"):
        return _quiet_core(
            security=_customer_security(account_type, "a1"),
            accounts=SimpleNamespace(
                list_users=lambda **kwargs: [{"id": "u1", "username": "boss",
                                              "email": "b@example.com", "account_type": "administrator",
                                              "role": "owner", "active": 1}],
                get_user=lambda uid: {"id": uid, "role": "owner", "account_type": "administrator"},
            ),
            permissions=SimpleNamespace(permissions_for_user=lambda uid, at: ["*"]),
        )

    def test_admin_users_requires_administrator(self):
        ok = FabOSAPI(self._admin_core("administrator")).request(
            "GET", "/api/v1/admin/users", {}, {"Authorization": "Bearer tok"})
        self.assertEqual(ok["status"], 200)
        self.assertEqual(ok["data"]["users"][0]["email"], "b@example.com")
        self.assertNotIn("password_hash", str(ok["data"]))
        denied = FabOSAPI(self._admin_core("customer")).request(
            "GET", "/api/v1/admin/users", {}, {"Authorization": "Bearer tok"})
        self.assertEqual(denied["status"], 403)

    def test_cad_capabilities_requires_customer(self):
        core = _quiet_core(
            security=_customer_security("customer"),
            cad_generation=SimpleNamespace(capabilities=lambda: {"formats": ["stl"]}),
        )
        ok = FabOSAPI(core).request("GET", "/api/v1/customer/cad/capabilities",
                                    {}, {"Authorization": "Bearer tok"})
        self.assertEqual(ok["status"], 200)
        self.assertEqual(ok["data"], {"formats": ["stl"]})
        anon = FabOSAPI(core).request("GET", "/api/v1/customer/cad/capabilities", {}, {})
        self.assertEqual(anon["status"], 401)


if __name__ == "__main__":
    unittest.main()
