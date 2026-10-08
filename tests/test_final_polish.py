"""Final polish round (2026-10-07), backend items.

1. Stripe/Square providers read credentials settings-first (admin settings
   UI), env fallback — mirroring the Resend provider pattern. Secrets never
   logged or exposed via API.
2. Customer orders LIST carries the same lightweight `fulfillment` summary
   as the detail endpoint, batched in one query (no N+1), on both transports.
3. `public_base_url` shop setting (empty default = current behavior):
   notification emails use absolute deep links when set, relative when empty.
4. Notification outbox: notify() only enqueues (fast, never raises); the
   automation reconcile tick drains it (bounded retries, backoff, dead-letter).
"""
import contextlib
import json
import logging
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI
from fabos_core.api import create_app
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.customer_notifications import (
    CustomerNotificationService, LoggingEmailProvider, NotificationSendError,
    ResendEmailProvider)
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.operations_hub import OperationsHubService
from fabos_core.services.payments import (
    PaymentProviderNotConfigured, PaymentService, SquarePaymentProvider,
    StripePaymentProvider)
from fabos_core.services.shop_settings import ShopSettingsService


FULFILLMENT_KEYS = ("carrier", "tracking_number", "tracking_url", "method",
                    "status", "packed_at", "shipped_at", "delivered_at",
                    "picked_up_at", "estimated_delivery")

STRIPE_ENV_KEYS = ("STRIPE_SECRET_KEY", "STRIPE_PUBLISHABLE_KEY",
                   "STRIPE_WEBHOOK_SECRET", "STRIPE_SUCCESS_URL",
                   "STRIPE_CANCEL_URL")
SQUARE_ENV_KEYS = ("SQUARE_ACCESS_TOKEN", "SQUARE_LOCATION_ID",
                   "SQUARE_WEBHOOK_SIGNATURE_KEY", "SQUARE_WEBHOOK_URL")


def _clear_env(test_case, *keys):
    saved = {key: os.environ.pop(key, None) for key in keys}

    def _restore():
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    test_case.addCleanup(_restore)
    return saved


class _Db:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "fabos.sqlite3")
        self.db.initialize()
        migrate(self.db)

    def close(self):
        self.tmp.cleanup()


class PaymentProviderSettingsTests(unittest.TestCase):
    def setUp(self):
        _clear_env(self, *(STRIPE_ENV_KEYS + SQUARE_ENV_KEYS + ("FABOS_PAYMENT_PROVIDER",)))

    def test_stripe_settings_win_over_env(self):
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_env_decoy"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_env_decoy"
        provider = StripePaymentProvider(shop_settings={
            "stripe_secret_key": "sk_test_from_settings",
            "stripe_webhook_secret": "whsec_from_settings",
            "stripe_success_url": "https://shop.example.com/success",
            "stripe_cancel_url": "https://shop.example.com/cancel",
        })
        self.assertEqual(provider.secret_key, "sk_test_from_settings")
        self.assertEqual(provider.webhook_secret, "whsec_from_settings")
        self.assertTrue(provider.test_mode)
        self.assertFalse(provider.live_mode)

    def test_stripe_env_fallback_when_settings_empty(self):
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_env_only"
        os.environ["STRIPE_WEBHOOK_SECRET"] = "whsec_env_only"
        provider = StripePaymentProvider(shop_settings={
            "stripe_secret_key": "   ",  # whitespace-only counts as empty
            "stripe_webhook_secret": "",
        })
        self.assertEqual(provider.secret_key, "sk_test_env_only")
        self.assertEqual(provider.webhook_secret, "whsec_env_only")

    def test_stripe_unconfigured_when_neither(self):
        with self.assertRaises(PaymentProviderNotConfigured):
            StripePaymentProvider(shop_settings={})

    def test_stripe_checkout_uses_settings_urls(self):
        provider = StripePaymentProvider(shop_settings={
            "stripe_secret_key": "sk_test_123",
            "stripe_success_url": "https://shop.example.com/success",
            "stripe_cancel_url": "https://shop.example.com/cancel",
        })
        captured = {}

        def fake_request(path, fields, idempotency_key=None):
            captured.update(fields)
            return {"id": "cs_test_1", "url": "https://checkout.stripe.com/x",
                    "payment_intent": "pi_1"}

        provider._request = fake_request
        result = provider.create_checkout(
            payment_id="pay-1", amount_cents=5000, currency="USD",
            metadata={"order_id": "o-1"})
        self.assertEqual(captured["success_url"], "https://shop.example.com/success")
        self.assertEqual(captured["cancel_url"], "https://shop.example.com/cancel")
        self.assertEqual(result["checkout_url"], "https://checkout.stripe.com/x")

    def test_stripe_checkout_requires_urls_from_either_source(self):
        provider = StripePaymentProvider(
            shop_settings={"stripe_secret_key": "sk_test_123"})
        with self.assertRaises(PaymentProviderNotConfigured):
            provider.create_checkout(
                payment_id="pay-1", amount_cents=5000, currency="USD",
                metadata={"order_id": "o-1"})

    def test_square_settings_win_over_env(self):
        os.environ["SQUARE_ACCESS_TOKEN"] = "env_decoy_token"
        os.environ["SQUARE_LOCATION_ID"] = "env_decoy_location"
        provider = SquarePaymentProvider(shop_settings={
            "square_access_token": "sq_settings_token",
            "square_location_id": "sq_settings_location",
            "square_webhook_signature_key": "sq_settings_sig",
            "square_webhook_url": "https://shop.example.com/square-webhook",
        })
        self.assertEqual(provider.access_token, "sq_settings_token")
        self.assertEqual(provider.location_id, "sq_settings_location")
        self.assertEqual(provider.webhook_signature_key, "sq_settings_sig")
        self.assertEqual(provider.webhook_url, "https://shop.example.com/square-webhook")

    def test_square_env_fallback_when_settings_empty(self):
        os.environ["SQUARE_ACCESS_TOKEN"] = "sq_env_token"
        os.environ["SQUARE_LOCATION_ID"] = "sq_env_location"
        provider = SquarePaymentProvider(shop_settings={"square_access_token": ""})
        self.assertEqual(provider.access_token, "sq_env_token")
        self.assertEqual(provider.location_id, "sq_env_location")

    def test_square_unconfigured_when_neither(self):
        with self.assertRaises(PaymentProviderNotConfigured):
            SquarePaymentProvider(shop_settings={})

    def test_payment_service_passes_shop_settings_through(self):
        hold = _Db()
        self.addCleanup(hold.close)
        os.environ["FABOS_PAYMENT_PROVIDER"] = "stripe"
        os.environ["STRIPE_SECRET_KEY"] = "sk_test_env_decoy"
        service = PaymentService(hold.db, accounts=None, invoices=None,
                                 shop_settings={"stripe_secret_key": "sk_test_svc_settings"})
        self.assertEqual(service.provider.secret_key, "sk_test_svc_settings")

    def test_payment_service_env_fallback_without_settings(self):
        hold = _Db()
        self.addCleanup(hold.close)
        os.environ["FABOS_PAYMENT_PROVIDER"] = "square"
        os.environ["SQUARE_ACCESS_TOKEN"] = "sq_env_token"
        os.environ["SQUARE_LOCATION_ID"] = "sq_env_location"
        service = PaymentService(hold.db, accounts=None, invoices=None)
        self.assertEqual(service.provider.access_token, "sq_env_token")

    def test_secrets_never_logged(self):
        secret = "sk_test_super_secret_value_abc123"
        messages = []

        class _Capture(logging.Handler):
            def emit(self, record):
                messages.append(record.getMessage())

        logger = logging.getLogger("fabos_core.services.payments")
        handler = _Capture()
        logger.addHandler(handler)
        try:
            StripePaymentProvider(shop_settings={"stripe_secret_key": secret})
            SquarePaymentProvider(shop_settings={
                "square_access_token": secret, "square_location_id": "loc"})
        finally:
            logger.removeHandler(handler)
        # The providers emit no logs at all today; this guards the invariant
        # that a secret value never reaches a log record.
        for message in messages:
            self.assertNotIn(secret, message)

    def test_secrets_masked_in_settings_snapshot(self):
        hold = _Db()
        self.addCleanup(hold.close)
        settings = ShopSettingsService(hold.db)
        secret = "sk_test_snapshot_secret_xyz"
        settings.set("stripe_secret_key", secret)
        settings.set("square_access_token", secret)
        snapshot = settings.masked_snapshot()
        self.assertEqual(snapshot["stripe_secret_key"], {"configured": True})
        self.assertEqual(snapshot["square_access_token"], {"configured": True})
        self.assertNotIn(secret, json.dumps(snapshot))
        # Non-secret payment keys stay plaintext (they are not secrets).
        settings.set("stripe_success_url", "https://shop.example.com/success")
        self.assertEqual(settings.masked_snapshot()["stripe_success_url"],
                         "https://shop.example.com/success")


class _QueryCounter:
    """Wrap a Database to count fulfillments-table queries (N+1 guard)."""
    def __init__(self, db):
        self._db = db
        self.fulfillment_queries = 0

    @contextlib.contextmanager
    def connect(self):
        with self._db.connect() as conn:
            def tracer(sql):
                if "fulfillments" in sql:
                    self.fulfillment_queries += 1

            conn.set_trace_callback(tracer)
            try:
                yield conn
            finally:
                conn.set_trace_callback(None)


def _fulfillment_accounts():
    return SimpleNamespace(
        get_user=lambda uid: {"id": uid, "active": 1, "account_type": "customer"},
        customer_for_user=lambda uid: {"id": "cust-1"},
    )


def _fulfillment_permissions():
    return SimpleNamespace(
        require=lambda *a, **k: True,
        has_permission=lambda *a, **k: True,
    )


class FulfillmentListPayloadTests(unittest.TestCase):
    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db
        self.service = FulfillmentService(self.db, _fulfillment_accounts(),
                                          _fulfillment_permissions())
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                ("cust-1", "List Customer", "list@example.com"))
            conn.commit()
        self.order_ids = []
        for n in range(3):
            oid = str(uuid.uuid4())
            with self.db.connect() as conn:
                conn.execute(
                    "INSERT INTO orders(id,order_number,status,total_cents,"
                    "customer_id) VALUES(?,?,?, ?,?)",
                    (oid, "O-LIST-%d" % n, "ready", 1000, "cust-1"))
                conn.commit()
            self.order_ids.append(oid)
        # Two of the three orders get fulfillment rows.
        self.service.save(self.order_ids[0], "shipping", "packed")
        self.service.update_for_user(
            "u1", self._fid(self.order_ids[0]),
            carrier="UPS", tracking_number="1Z1")
        self.service.save(self.order_ids[1], "pickup", "ready_for_pickup")

    def _fid(self, order_id):
        with self.db.connect() as conn:
            return conn.execute(
                "SELECT id FROM fulfillments WHERE order_id=?",
                (order_id,)).fetchone()["id"]

    def test_batched_payloads_match_detail_shape(self):
        payloads = self.service.customer_payloads_for_orders(self.order_ids)
        self.assertEqual(set(payloads.keys()), set(self.order_ids))
        for payload in payloads.values():
            self.assertEqual(tuple(sorted(payload.keys())),
                             tuple(sorted(FULFILLMENT_KEYS)))
        shipped = payloads[self.order_ids[0]]
        self.assertEqual(shipped["carrier"], "UPS")
        self.assertEqual(shipped["tracking_number"], "1Z1")
        self.assertEqual(shipped["tracking_url"],
                         "https://www.ups.com/track?tracknum=1Z1")
        self.assertEqual(shipped["method"], "shipping")
        self.assertEqual(shipped["status"], "packed")
        # Order with no fulfillment row: same shape, nulls where unknown.
        missing = payloads[self.order_ids[2]]
        self.assertTrue(all(v is None for v in missing.values()))
        self.assertEqual(missing,
                         FulfillmentService.customer_payload(None))

    def test_batched_lookup_is_single_query(self):
        counter = _QueryCounter(self.db)
        service = FulfillmentService(counter, _fulfillment_accounts(),
                                     _fulfillment_permissions())
        service.customer_payloads_for_orders(self.order_ids)
        self.assertEqual(counter.fulfillment_queries, 1)

    def test_batched_lookup_empty_input(self):
        self.assertEqual(self.service.customer_payloads_for_orders([]), {})
        self.assertEqual(self.service.customer_payloads_for_orders(None), {})

    def _fastapi_client(self):
        rows = [
            {"id": oid, "order_number": "O-LIST-%d" % n, "status": "ready",
             "total_cents": 1000}
            for n, oid in enumerate(self.order_ids)
        ]
        core = SimpleNamespace(
            database=self.db,
            fulfillment=self.service,
            orders=SimpleNamespace(list_for_user=lambda uid: rows),
        )
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "u1", "account_type": "customer", "role": ""}
        return TestClient(app)

    def test_fastapi_list_carries_fulfillment(self):
        response = self._fastapi_client().get("/api/v1/customer/orders")
        self.assertEqual(response.status_code, 200)
        orders = {o["id"]: o for o in response.json()["orders"]}
        self.assertEqual(set(orders.keys()), set(self.order_ids))
        for order in orders.values():
            self.assertEqual(tuple(sorted(order["fulfillment"].keys())),
                             tuple(sorted(FULFILLMENT_KEYS)))
        self.assertEqual(orders[self.order_ids[0]]["fulfillment"]["carrier"], "UPS")
        self.assertEqual(
            orders[self.order_ids[0]]["fulfillment"]["tracking_number"], "1Z1")
        self.assertEqual(orders[self.order_ids[1]]["fulfillment"]["method"], "pickup")
        self.assertTrue(
            all(v is None for v in orders[self.order_ids[2]]["fulfillment"].values()))

    def _wsgi_api(self):
        rows = [
            {"id": oid, "order_number": "O-LIST-%d" % n, "status": "ready",
             "total_cents": 1000}
            for n, oid in enumerate(self.order_ids)
        ]
        core = SimpleNamespace(
            database=self.db,
            fulfillment=self.service,
            shop_settings={},
            orders=SimpleNamespace(list_for_user=lambda uid: rows),
            security=SimpleNamespace(
                context=lambda token, permission=None: {
                    "id": "u1", "account_type": "customer"}),
            accounts=SimpleNamespace(get_user=lambda uid: {"id": uid, "role": "owner"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        return FabOSAPI(core), {"Authorization": "Bearer <redacted>"}

    def test_wsgi_list_carries_fulfillment(self):
        api, headers = self._wsgi_api()
        result = api.request("GET", "/api/v1/customer/orders", {}, headers)
        self.assertEqual(result["status"], 200)
        orders = {o["id"]: o for o in result["data"]["orders"]}
        self.assertEqual(set(orders.keys()), set(self.order_ids))
        for order in orders.values():
            self.assertEqual(tuple(sorted(order["fulfillment"].keys())),
                             tuple(sorted(FULFILLMENT_KEYS)))
        self.assertEqual(orders[self.order_ids[0]]["fulfillment"]["carrier"], "UPS")
        self.assertTrue(
            all(v is None for v in orders[self.order_ids[2]]["fulfillment"].values()))


class PublicBaseUrlTests(unittest.TestCase):
    def setUp(self):
        _clear_env(self, "RESEND_API_KEY", "RESEND_FROM_EMAIL")
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                ("cust-1", "Test Customer", "customer@example.com"))
            conn.commit()
        self.settings = ShopSettingsService(self.db)

    def test_setting_defaults_to_empty_with_meta(self):
        self.assertEqual(self.settings.get("public_base_url", "UNSET"), "")
        meta = self.settings.metadata()
        self.assertIn("public_base_url", meta["notifications"])
        self.assertTrue(meta["notifications"]["public_base_url"])
        # Plain string: settable, and NOT a masked secret.
        self.settings.set("public_base_url", "https://shop.example.com")
        self.assertEqual(self.settings.masked_snapshot()["public_base_url"],
                         "https://shop.example.com")

    def _notify_quote(self):
        service = CustomerNotificationService(self.db, self.settings)
        record_id = service.notify(
            "quote_sent", "cust-1", entity_type="quote", entity_id="q-1",
            title="Quote ready", body="Ready for review.",
            deep_link="/quote.html?id=q-1", dedupe_key="base-url-test")
        self.assertIsNotNone(record_id)
        return record_id

    def _outbox_row(self, record_id):
        with self.db.connect() as conn:
            return dict(conn.execute(
                "SELECT * FROM notification_outbox WHERE notification_id=?",
                (record_id,)).fetchone())

    def _record(self, record_id):
        with self.db.connect() as conn:
            return dict(conn.execute(
                "SELECT * FROM customer_notifications WHERE id=?",
                (record_id,)).fetchone())

    def test_empty_setting_keeps_relative_links(self):
        self.settings.set("public_base_url", "")
        record_id = self._notify_quote()
        outbox = self._outbox_row(record_id)
        self.assertIn("View: /quote.html?id=q-1", outbox["text_body"])
        # The in-app record always keeps the relative deep link.
        self.assertEqual(self._record(record_id)["deep_link"], "/quote.html?id=q-1")

    def test_setting_produces_absolute_links(self):
        self.settings.set("public_base_url", "https://shop.example.com")
        record_id = self._notify_quote()
        outbox = self._outbox_row(record_id)
        self.assertIn("View: https://shop.example.com/quote.html?id=q-1",
                      outbox["text_body"])
        self.assertEqual(self._record(record_id)["deep_link"], "/quote.html?id=q-1")

    def test_trailing_slash_is_trimmed(self):
        self.settings.set("public_base_url", "https://shop.example.com/")
        record_id = self._notify_quote()
        outbox = self._outbox_row(record_id)
        self.assertIn("View: https://shop.example.com/quote.html?id=q-1",
                      outbox["text_body"])
        self.assertNotIn("example.com//quote", outbox["text_body"])

    def test_absolute_link_helper_edge_cases(self):
        service = CustomerNotificationService(self.db, self.settings)
        self.settings.set("public_base_url", "https://shop.example.com")
        self.assertEqual(service._absolute_link("/a/b"), "https://shop.example.com/a/b")
        self.assertEqual(service._absolute_link(""), "")
        self.assertEqual(service._absolute_link(None), "")
        self.assertEqual(service._absolute_link("https://other.example/x"),
                         "https://other.example/x")
        self.settings.set("public_base_url", "")
        self.assertEqual(service._absolute_link("/a/b"), "/a/b")


class _FakeEmailProvider:
    name = "fake"

    def __init__(self, fail_with=None):
        self.fail_with = fail_with
        self.sent = []

    def send_email(self, *, to, subject, text_body, from_email):
        if self.fail_with is not None:
            raise self.fail_with
        self.sent.append({"to": to, "subject": subject,
                          "text_body": text_body, "from_email": from_email})
        return {"provider": "fake", "status": "sent", "id": "fake-1"}


class NotificationOutboxTests(unittest.TestCase):
    def setUp(self):
        _clear_env(self, "RESEND_API_KEY", "RESEND_FROM_EMAIL")
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                ("cust-1", "Test Customer", "customer@example.com"))
            conn.commit()

    def _service(self, provider):
        return CustomerNotificationService(self.db, shop_settings={}, provider=provider)

    def _notify(self, service):
        return service.notify(
            "quote_sent", "cust-1", entity_type="quote", entity_id="q-1",
            title="Quote ready", body="Ready for review.",
            deep_link="/quote.html?id=q-1",
            dedupe_key="outbox-test-%s" % uuid.uuid4().hex)

    def _outbox_rows(self):
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM notification_outbox ORDER BY created_at").fetchall()]

    def _record(self, record_id):
        with self.db.connect() as conn:
            return dict(conn.execute(
                "SELECT * FROM customer_notifications WHERE id=?",
                (record_id,)).fetchone())

    def test_notify_enqueues_without_sending(self):
        provider = _FakeEmailProvider()
        service = self._service(provider)
        record_id = self._notify(service)
        self.assertIsNotNone(record_id)
        # Hook path never touches the provider: fast, never raises.
        self.assertEqual(provider.sent, [])
        rows = self._outbox_rows()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["notification_id"], record_id)
        self.assertEqual(row["status"], "queued")
        self.assertEqual(row["attempts"], 0)
        self.assertEqual(row["to_email"], "customer@example.com")
        self.assertIn("Quote ready", row["subject"])
        channels = json.loads(self._record(record_id)["channels_json"])
        self.assertEqual(channels["email"]["status"], "queued")
        self.assertEqual(channels["email"]["outbox_id"], row["id"])

    def test_drain_sends_and_marks_sent(self):
        provider = _FakeEmailProvider()
        service = self._service(provider)
        record_id = self._notify(service)
        sent, failed = service.drain_outbox()
        self.assertEqual((sent, failed), (1, 0))
        self.assertEqual(len(provider.sent), 1)
        self.assertEqual(provider.sent[0]["to"], "customer@example.com")
        rows = self._outbox_rows()
        self.assertEqual(rows[0]["status"], "sent")
        channels = json.loads(self._record(record_id)["channels_json"])
        self.assertEqual(channels["email"]["status"], "sent")
        self.assertEqual(channels["email"]["provider"], "fake")

    def _force_due(self):
        """Simulate the retry backoff elapsing."""
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE notification_outbox SET next_attempt_at='2000-01-01 00:00:00'")
            conn.commit()

    def test_drain_retries_with_backoff_then_dead_letters(self):
        provider = _FakeEmailProvider(fail_with=NotificationSendError("boom"))
        service = self._service(provider)
        record_id = self._notify(service)
        # Attempts 1..4 -> failed with backoff; attempt 5 -> dead.
        for attempt in range(1, 5):
            self._force_due()
            sent, failed = service.drain_outbox()
            self.assertEqual((sent, failed), (0, 1))
            row = self._outbox_rows()[0]
            self.assertEqual(row["status"], "failed")
            self.assertEqual(row["attempts"], attempt)
            self.assertIn("boom", row["last_error"])
        self._force_due()
        sent, failed = service.drain_outbox()
        self.assertEqual((sent, failed), (0, 1))
        row = self._outbox_rows()[0]
        self.assertEqual(row["status"], "dead")
        self.assertEqual(row["attempts"], 5)
        # Dead rows are never picked up again.
        sent, failed = service.drain_outbox()
        self.assertEqual((sent, failed), (0, 0))
        channels = json.loads(self._record(record_id)["channels_json"])
        self.assertEqual(channels["email"]["status"], "failed")
        self.assertIn("boom", channels["email"]["error"])

    def test_drain_never_raises_on_unexpected_provider_error(self):
        provider = _FakeEmailProvider(fail_with=RuntimeError("provider bug"))
        service = self._service(provider)
        record_id = self._notify(service)
        sent, failed = service.drain_outbox()  # must not raise
        self.assertEqual((sent, failed), (0, 1))
        row = self._outbox_rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)

    def test_drain_respects_limit(self):
        provider = _FakeEmailProvider()
        service = self._service(provider)
        for _ in range(3):
            self._notify(service)
        sent, failed = service.drain_outbox(limit=2)
        self.assertEqual((sent, failed), (2, 0))
        self.assertEqual(len(provider.sent), 2)
        sent, failed = service.drain_outbox(limit=2)
        self.assertEqual((sent, failed), (1, 0))

    def test_reconcile_tick_drains_outbox(self):
        # End-to-end: enqueue via the hook path, drain via the automation
        # reconcile tick (operations_hub), which is where quote_expiring
        # hooks already fire.
        service = CustomerNotificationService(self.db, shop_settings={},
                                              provider=_FakeEmailProvider())
        record_id = self._notify(service)
        rows = self._outbox_rows()
        self.assertEqual(rows[0]["status"], "queued")
        hub = OperationsHubService(SimpleNamespace(database=self.db))
        hub.reconcile_workflows()
        rows = self._outbox_rows()
        self.assertEqual(rows[0]["status"], "sent")
        channels = json.loads(self._record(record_id)["channels_json"])
        # Reconcile drains with the default (log fallback) provider, whose
        # reported status is "logged" — same as the old synchronous path.
        self.assertEqual(channels["email"]["status"], "logged")
        self.assertEqual(channels["email"]["provider"], "log")

    def test_outbox_table_created_by_migration(self):
        # migrate() (not _ensure_outbox_schema) must create the table on a
        # fresh database: drop it, forget version 60, re-run migrate.
        with self.db.connect() as conn:
            conn.execute("DROP TABLE notification_outbox")
            conn.execute("DELETE FROM app_migrations WHERE version=60")
            conn.commit()
        migrate(self.db)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name='notification_outbox'").fetchone()
        self.assertIsNotNone(row)

    def _orphan_sending(self, stale=True, attempts=0):
        provider = _FakeEmailProvider()
        service = self._service(provider)
        self._notify(service)
        row = self._outbox_rows()[0]
        updated_at = ("2000-01-01 00:00:00" if stale
                      else "2999-01-01 00:00:00")
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE notification_outbox SET status='sending',"
                " updated_at=?, attempts=? WHERE id=?",
                (updated_at, attempts, row["id"]))
            conn.commit()
        return service, row["id"]

    def test_drain_recovers_stale_sending_claim(self):
        # A drain that crashed between the 'sending' claim and the provider
        # call orphans the row in 'sending'; the next drain must recover it
        # (re-queue with backoff) instead of leaving the email unsent forever.
        service, outbox_id = self._orphan_sending(stale=True, attempts=0)
        sent, failed = service.drain_outbox()  # recovery runs; backoff pending
        self.assertEqual((sent, failed), (0, 0))
        row = self._outbox_rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["attempts"], 1)
        self.assertIn("stale sending claim", row["last_error"])
        # Backoff elapses: the email goes out on a later drain.
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE notification_outbox "
                "SET next_attempt_at='2000-01-01 00:00:00'")
            conn.commit()
        sent, failed = service.drain_outbox()
        self.assertEqual((sent, failed), (1, 0))
        row = self._outbox_rows()[0]
        self.assertEqual(row["status"], "sent")

    def test_drain_ignores_fresh_sending_claim(self):
        # A row claimed seconds ago belongs to a live concurrent drain —
        # recovery must not steal it.
        service, outbox_id = self._orphan_sending(stale=False, attempts=0)
        sent, failed = service.drain_outbox()
        self.assertEqual((sent, failed), (0, 0))
        row = self._outbox_rows()[0]
        self.assertEqual(row["status"], "sending")

    def test_stale_sending_claim_with_exhausted_attempts_dead_letters(self):
        service, outbox_id = self._orphan_sending(stale=True, attempts=5)
        sent, failed = service.drain_outbox()
        self.assertEqual((sent, failed), (0, 0))
        row = self._outbox_rows()[0]
        self.assertEqual(row["status"], "dead")
        self.assertEqual(row["attempts"], 5)


if __name__ == "__main__":
    unittest.main()
