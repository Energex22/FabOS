"""Phase 2 transactional notifications: emission hooks, dispatch, customer API.

Covers the six customer events (quote sent / quote expiring / proof sent /
proof changes_requested / payment failed / order shipped / order cancelled),
the no-key log fallback, channel-preference handling, the expiring-quote
dedupe, and the customer notification API (auth scoping, pagination,
mark-read) on the WSGI transport, which mirrors the FastAPI routes.
"""
import json
import logging
import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

from fabos_api import FabOSAPI
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services import notifications as notifications_mod
from fabos_core.services.customer_notifications import (
    CustomerNotificationService, LoggingEmailProvider, ResendEmailProvider,
    normalize_notification_preference)
from fabos_core.services.customers import CustomerService
from fabos_core.services.design_proofs import DesignProofService
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.operations_hub import OperationsHubService
from fabos_core.services.orders import OrderService
from fabos_core.services.payments import PaymentService
from fabos_core.services.quotes import QuoteService


class _Security:
    def context(self, token, permission=None):
        if token == "customer-token":
            return {"id": "customer-user", "account_type": "customer"}
        if token == "other-token":
            return {"id": "other-user", "account_type": "customer"}
        if token == "staff-token":
            return {"id": "staff-user", "account_type": "employee"}
        raise PermissionError("Invalid or expired session")


class _Accounts:
    def __init__(self, links):
        self.links = links

    def customer_for_user(self, user_id):
        return self.links.get(user_id)


def _no_resend_env(test_case):
    """Ensure RESEND_API_KEY / RESEND_FROM_EMAIL are unset for a test."""
    saved = {key: os.environ.pop(key, None)
             for key in ("RESEND_API_KEY", "RESEND_FROM_EMAIL")}

    def _restore():
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    test_case.addCleanup(_restore)


class NotificationFixture(unittest.TestCase):
    def setUp(self):
        _no_resend_env(self)
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "fabos.db")
        self.db.initialize()
        migrate(self.db)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) VALUES(?,?,?,?,?,?)",
                ("customer-user", "customer", "unused", "customer", 1, "customer"))
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) VALUES(?,?,?,?,?,?)",
                ("other-user", "other", "unused", "customer", 1, "customer"))
            conn.execute(
                "INSERT INTO customers(id,name,email,phone) VALUES(?,?,?,?)",
                ("customer-1", "Test Customer", "customer@example.com", "555-0100"))
            conn.execute(
                "INSERT INTO customers(id,name,email,phone) VALUES(?,?,?,?)",
                ("customer-2", "Other Customer", "other@example.com", "555-0200"))
            conn.execute("INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)",
                         ("customer-user", "customer-1"))
            conn.execute("INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)",
                         ("other-user", "customer-2"))
            conn.commit()
        self.service = CustomerNotificationService(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def _records(self, customer_id="customer-1"):
        with self.db.connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM customer_notifications WHERE customer_id=? ORDER BY created_at",
                (customer_id,)).fetchall()]

    def _channels(self, record):
        return json.loads(record["channels_json"] or "{}")


class EmissionTests(NotificationFixture):
    def test_quote_sent_creates_record_with_deep_link(self):
        quotes = QuoteService(self.db)
        quote_id = quotes.save(
            {"customer_id": "customer-1", "status": "sent",
             "expires_at": (date.today() + timedelta(days=14)).isoformat(), "notes": ""},
            [{"description": "Widget", "quantity": 1, "unit_price_cents": 2500}])
        records = self._records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_type"], "quote_sent")
        self.assertEqual(record["entity_type"], "quote")
        self.assertEqual(record["entity_id"], quote_id)
        self.assertEqual(record["deep_link"], "/quote.html?id=%s" % quote_id)
        self.assertIn("ready", record["title"].lower())
        self.assertEqual(record["is_read"], 0)
        # No RESEND_API_KEY -> logged instead of sent.
        self.assertEqual(self._channels(record)["email"]["status"], "logged")

    def test_quote_sent_does_not_fire_twice(self):
        quotes = QuoteService(self.db)
        quote_id = quotes.save(
            {"customer_id": "customer-1", "status": "sent"},
            [{"description": "Widget", "quantity": 1, "unit_price_cents": 100}])
        quotes.set_status(quote_id, "sent")  # no transition; must not re-emit
        quotes.save({"customer_id": "customer-1", "status": "sent"},
                    [{"description": "Widget", "quantity": 1, "unit_price_cents": 100}],
                    quote_id=quote_id)
        self.assertEqual(len(self._records()), 1)

    def test_quote_expiring_emits_once_via_reconcile(self):
        expires = (date.today() + timedelta(days=3)).isoformat()
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents,expires_at) "
                "VALUES(?,?,?,?,?,?)",
                ("quote-exp", "Q-EXP-1", "customer-1", "sent", 9900, expires))
            conn.commit()
        hub = OperationsHubService(SimpleNamespace(database=self.db))
        hub.reconcile_workflows()
        hub.reconcile_workflows()  # second run must not duplicate
        records = self._records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_type"], "quote_expiring")
        self.assertEqual(record["deep_link"], "/quote.html?id=quote-exp")
        self.assertIn("3 days", record["title"])

    def test_quote_expiring_ignores_other_dates(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents,expires_at) "
                "VALUES(?,?,?,?,?,?)",
                ("quote-far", "Q-FAR-1", "customer-1", "sent", 100,
                 (date.today() + timedelta(days=9)).isoformat()))
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents,expires_at) "
                "VALUES(?,?,?,?,?,?)",
                ("quote-draft", "Q-D-1", "customer-1", "draft", 100,
                 (date.today() + timedelta(days=3)).isoformat()))
            conn.commit()
        OperationsHubService(SimpleNamespace(database=self.db)).reconcile_workflows()
        self.assertEqual(self._records(), [])

    def _proof_fixture(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("quote-1", "Q-TEST-0001", "customer-1", "accepted", 4200))
            conn.execute(
                "INSERT INTO designs(id,product_id,name,current_version) VALUES(?,?,?,?)",
                ("design-1", None, "Customer Part", 1))
            conn.execute(
                "INSERT INTO design_versions(id,design_id,version,label) VALUES(?,?,?,?)",
                ("design-version-1", "design-1", 1, "Customer upload"))
            conn.execute("INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)",
                         ("quote-1", "design-1"))
            conn.commit()
        vault = DesignVaultService(self.db, self.temp.name)
        return DesignProofService(self.db, vault)

    def test_proof_sent_and_changes_requested(self):
        proofs = self._proof_fixture()
        proof = proofs.create("quote-1", customer_note="Review the fit")
        proofs.send(proof["id"])
        sent = self._records()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0]["event_type"], "proof_sent")
        self.assertEqual(sent[0]["deep_link"], "/quote.html?id=quote-1#proof")
        self.assertIn("Review the fit", sent[0]["body"])

        proofs.request_changes("customer-user", proof["id"], "Make it taller")
        records = self._records()
        self.assertEqual(len(records), 2)
        changes = [r for r in records if r["event_type"] == "proof_changes_requested"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["deep_link"], "/quote.html?id=quote-1#proof")
        self.assertIn("Make it taller", changes[0]["body"])

    def test_proof_changes_requested_stub_is_real_with_service(self):
        receipt = notifications_mod.notify_proof_changes_requested(
            {"id": "p-stub", "quote_id": "missing", "design_version": 1},
            service=self.service)
        self.assertFalse(receipt["notified"])
        self.assertIsNone(receipt["notification_id"])

    def test_proof_changes_requested_stub_stays_log_only_without_service(self):
        with self.assertLogs("fabos_core.services.notifications", level="INFO") as captured:
            receipt = notifications_mod.notify_proof_changes_requested(
                {"id": "p-log", "quote_id": "q", "quote_number": "Q-1", "design_version": 2})
        self.assertTrue(receipt["notified"])
        self.assertEqual(receipt["channel"], "log")
        self.assertTrue(any("p-log" in message for message in captured.output))

    def test_payment_failed_emission(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("order-1", "O-TEST-0001", "customer-1", "confirmed", 5000))
            conn.execute(
                "INSERT INTO payment_transactions(id,order_id,amount_cents,currency,provider,status) "
                "VALUES(?,?,?,?,?,?)",
                ("pay-1", "order-1", 5000, "USD", "unconfigured", "pending"))
            conn.commit()
        payments = PaymentService(self.db, accounts=None, invoices=None)
        payments._set_status("pay-1", "failed")
        records = self._records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_type"], "payment_failed")
        self.assertEqual(record["entity_id"], "order-1")
        self.assertEqual(record["deep_link"], "/order.html?id=order-1")
        self.assertIn("$50.00", record["body"])
        # A repeated failed set is not a new transition: still one record.
        payments._set_status("pay-1", "failed")
        self.assertEqual(len(self._records()), 1)

    def test_order_shipped_emission_includes_carrier_and_tracking(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("order-2", "O-TEST-0002", "customer-1", "ready", 1200))
            conn.commit()
        fulfillment = FulfillmentService(self.db)
        fulfillment.save("order-2", "shipping", "shipped", carrier="UPS", tracking="1Z999AA")
        records = self._records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_type"], "order_shipped")
        self.assertEqual(record["deep_link"], "/order.html?id=order-2")
        self.assertIn("UPS", record["body"])
        self.assertIn("1Z999AA", record["body"])
        # Re-saving the same shipped state does not re-emit.
        fulfillment.save("order-2", "shipping", "shipped", carrier="UPS", tracking="1Z999AA")
        self.assertEqual(len(self._records()), 1)

    def test_order_cancelled_includes_reason_and_refund(self):
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO orders(id,order_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                ("order-3", "O-TEST-0003", "customer-1", "confirmed", 3000))
            conn.execute(
                "INSERT INTO invoices(id,invoice_number,order_id,total_cents,paid_cents,status) "
                "VALUES(?,?,?,?,?,?)",
                ("inv-3", "INV-3", "order-3", 3000, 3000, "paid"))
            conn.execute(
                "INSERT INTO payments(id,invoice_id,amount_cents,method) VALUES(?,?,?,?)",
                ("pmt-3", "inv-3", 3000, "card"))
            conn.commit()
        orders = OrderService(self.db)
        orders.set_status_internal("order-3", "cancelled", reason="Customer asked to cancel")
        records = self._records()
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["event_type"], "order_cancelled")
        self.assertEqual(record["deep_link"], "/order.html?id=order-3")
        self.assertIn("Customer asked to cancel", record["body"])
        self.assertIn("$30.00", record["body"])


class PreferenceDispatchTests(NotificationFixture):
    def _notify(self, preference):
        with self.db.connect() as conn:
            conn.execute("UPDATE customers SET notification_preference=? WHERE id=?",
                         (preference, "customer-1"))
            conn.commit()
        return self.service.notify(
            "quote_sent", "customer-1", entity_type="quote", entity_id="q-1",
            title="Quote ready", body="Ready.", deep_link="/quote.html?id=q-1",
            dedupe_key="pref-test:%s" % preference)

    def test_default_preference_is_email(self):
        self.assertEqual(normalize_notification_preference(None), "email")
        self.assertEqual(normalize_notification_preference("carrier-pigeon"), "email")

    def test_no_key_fallback_logs_email_instead_of_sending(self):
        with self.assertLogs("fabos_core.services.customer_notifications", level="INFO") as captured:
            record_id = self._notify("email")
        self.assertIsNotNone(record_id)
        record = self._records()[0]
        self.assertEqual(json.loads(record["channels_json"])["email"]["status"], "logged")
        self.assertTrue(any("logged, not sent" in message for message in captured.output))

    def test_sms_preference_logs_sms_and_skips_email(self):
        record_id = self._notify("sms")
        record = self._records()[0]
        channels = json.loads(record["channels_json"])
        self.assertNotIn("email", channels)
        self.assertEqual(channels["sms"]["status"], "pending_sms_provider")

    def test_both_preference_attempts_email_and_marks_sms_pending(self):
        record_id = self._notify("both")
        record = self._records()[0]
        channels = json.loads(record["channels_json"])
        self.assertEqual(channels["email"]["status"], "logged")
        self.assertEqual(channels["sms"]["status"], "pending_sms_provider")

    def test_resend_provider_is_used_when_key_configured(self):
        os.environ["RESEND_API_KEY"] = "re_test_key"
        service = CustomerNotificationService(self.db)
        self.assertIsInstance(service.provider, ResendEmailProvider)

    def test_resend_provider_posts_expected_request(self):
        import io
        from unittest import mock

        captured = {}

        class _Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return b'{"id": "re_123"}'

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = dict(request.header_items())
            captured["payload"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response()

        provider = ResendEmailProvider(api_key="re_test_key")
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            receipt = provider.send_email(
                to="customer@example.com", subject="FABVEX: Quote ready",
                text_body="Your quote is ready.", from_email="FABVEX <hello@fabvex.com>")
        self.assertEqual(captured["url"], "https://api.resend.com/emails")
        self.assertEqual(captured["headers"]["Authorization"], "Bearer re_test_key")
        self.assertEqual(captured["payload"]["from"], "FABVEX <hello@fabvex.com>")
        self.assertEqual(captured["payload"]["to"], ["customer@example.com"])
        self.assertEqual(captured["payload"]["subject"], "FABVEX: Quote ready")
        self.assertEqual(receipt, {"provider": "resend", "status": "sent", "id": "re_123"})

    def test_resend_provider_refuses_without_key(self):
        provider = ResendEmailProvider(api_key="")
        from fabos_core.services.customer_notifications import NotificationSendError
        with self.assertRaises(NotificationSendError):
            provider.send_email(to="a@b.com", subject="s", text_body="b",
                                from_email="FABVEX <hello@fabvex.com>")

    def test_log_provider_used_without_key(self):
        self.assertIsInstance(self.service.provider, LoggingEmailProvider)

    def test_customer_save_persists_preference(self):
        customers = CustomerService(self.db)
        customers.save({"notification_preference": "both"}, customer_id="customer-1")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT notification_preference FROM customers WHERE id=?", ("customer-1",)).fetchone()
        self.assertEqual(row["notification_preference"], "both")
        # Invalid values normalize to the default instead of failing.
        customers.save({"notification_preference": "smoke-signal"}, customer_id="customer-1")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT notification_preference FROM customers WHERE id=?", ("customer-1",)).fetchone()
        self.assertEqual(row["notification_preference"], "email")


class NotificationApiTests(NotificationFixture):
    def setUp(self):
        super().setUp()
        self.api = FabOSAPI(SimpleNamespace(
            security=_Security(),
            accounts=_Accounts({
                "customer-user": {"id": "customer-1", "name": "Test Customer",
                                  "email": "customer@example.com", "phone": "555-0100"},
                "other-user": {"id": "customer-2", "name": "Other Customer",
                               "email": "other@example.com", "phone": "555-0200"},
            }),
            database=self.db,
            shop_settings=SimpleNamespace(get=lambda key, default="": default),
        ))
        self.headers = {"Authorization": "Bearer customer-token"}
        self.other_headers = {"Authorization": "Bearer other-token"}
        self.staff_headers = {"Authorization": "Bearer staff-token"}

    def _seed(self, count, customer_id="customer-1"):
        for index in range(count):
            self.service.notify(
                "quote_sent", customer_id, entity_type="quote", entity_id="q-%d" % index,
                title="Quote %d ready" % index, body="Ready.",
                deep_link="/quote.html?id=q-%d" % index,
                dedupe_key="api-seed:%s:%d" % (customer_id, index))

    def test_list_is_unread_first_and_paginated(self):
        self._seed(30)
        result = self.api.request("GET", "/api/v1/customer/notifications?page=1&per_page=10",
                                  None, self.headers)
        self.assertEqual(result["status"], 200)
        data = result["data"]
        self.assertEqual(len(data["notifications"]), 10)
        self.assertEqual(data["total"], 30)
        self.assertEqual(data["unread"], 30)
        self.assertTrue(all("is_read" in n and "deep_link" in n for n in data["notifications"]))
        second = self.api.request("GET", "/api/v1/customer/notifications?page=3&per_page=10",
                                  None, self.headers)
        self.assertEqual(len(second["data"]["notifications"]), 10)
        ids_first = {n["id"] for n in data["notifications"]}
        ids_third = {n["id"] for n in second["data"]["notifications"]}
        self.assertTrue(ids_first.isdisjoint(ids_third))

    def test_unread_first_ordering(self):
        self._seed(3)
        first_id = self._records()[0]["id"]
        self.service.mark_read("customer-1", first_id)
        result = self.api.request("GET", "/api/v1/customer/notifications?per_page=25",
                                  None, self.headers)
        flags = [n["is_read"] for n in result["data"]["notifications"]]
        self.assertEqual(flags, [False, False, True])

    def test_unread_count_endpoint(self):
        self._seed(4)
        result = self.api.request("GET", "/api/v1/customer/notifications/unread-count",
                                  None, self.headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["unread"], 4)

    def test_mark_single_read(self):
        self._seed(2)
        target = self._records()[0]["id"]
        result = self.api.request("POST", "/api/v1/customer/notifications/%s/read" % target,
                                  {}, self.headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["unread"], 1)
        with self.db.connect() as conn:
            is_read = conn.execute(
                "SELECT is_read FROM customer_notifications WHERE id=?", (target,)).fetchone()["is_read"]
        self.assertEqual(is_read, 1)

    def test_mark_read_missing_is_404(self):
        result = self.api.request("POST", "/api/v1/customer/notifications/nope/read",
                                  {}, self.headers)
        self.assertEqual(result["status"], 404)

    def test_mark_all_read(self):
        self._seed(5)
        result = self.api.request("POST", "/api/v1/customer/notifications/read-all", {},
                                  self.headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["marked"], 5)
        self.assertEqual(result["data"]["unread"], 0)
        self.assertEqual(self.service.unread_count("customer-1"), 0)

    def test_auth_scoping_other_customer_sees_nothing(self):
        self._seed(3, customer_id="customer-1")
        result = self.api.request("GET", "/api/v1/customer/notifications", None, self.other_headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["total"], 0)
        self.assertEqual(result["data"]["unread"], 0)
        # And cannot mark another customer's notification as read.
        target = self._records("customer-1")[0]["id"]
        result = self.api.request("POST", "/api/v1/customer/notifications/%s/read" % target,
                                  {}, self.other_headers)
        self.assertEqual(result["status"], 404)

    def test_unauthenticated_is_rejected(self):
        result = self.api.request("GET", "/api/v1/customer/notifications", None, {})
        self.assertIn(result["status"], (401, 403))

    def test_staff_without_customer_link_is_rejected(self):
        result = self.api.request("GET", "/api/v1/customer/notifications", None, self.staff_headers)
        self.assertEqual(result["status"], 403)


if __name__ == "__main__":
    unittest.main()
