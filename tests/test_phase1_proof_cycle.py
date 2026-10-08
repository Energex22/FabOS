"""Phase 1 (proof cycle) backend regression tests.

Covers the Phase 1 backend build from the FABVEX build plan:
1. ``expires_at`` is exposed in the customer quote payload (FastAPI
   ``_quote_payload`` and the shared ``_public_quote`` projection).
2. ``quote_validity_days`` is a first-class shop setting (default 14, with
   human-readable metadata and numeric validation) and drives every
   quote-expiry computation instead of a hardcoded 14 days.
3. A proof transition to ``changes_requested`` fires the
   ``notify_proof_changes_requested`` hook (log-only in Phase 1).
4. Admin proof endpoints cover the Proofs workspace: global list filterable
   by status, single-proof view (with the customer's change-request comment
   and the staff note), plus a status filter on the per-quote list — on both
   the FastAPI registration and the WSGI mirror.
5. A per-revision staff note is stored on the proof and returned through the
   admin projection (and never leaks into the customer projection).
6. ``draft_proof_message`` exists as a stubbed AI-drafting seam and
   deliberately raises NotImplementedError.
"""
import logging
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from fabos_api import FabOSAPI
from fabos_core.api import _quote_payload, _order_payload
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services import notifications
from fabos_core.services.customer_api_writes import _public_quote
from fabos_core.services.design_proofs import DesignProofService
from fabos_core.services.design_proofs_api import (
    ProofComment,
    ProofCreateRequest,
    register_design_proof_routes,
)
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.shop_settings import ShopSettingsService


class _Security:
    def context(self, token, permission=None):
        if token == "admin-token":
            return {"id": "admin-user", "account_type": "administrator"}
        raise PermissionError("Invalid or expired session")


class _Log:
    def error(self, title, exc):
        pass


class _FakeApp:
    """Captures FastAPI route registrations so endpoints can be invoked directly."""

    def __init__(self):
        self.routes = {}

    def get(self, path):
        def deco(fn):
            self.routes[("GET", path)] = fn
            return fn

        return deco

    def post(self, path):
        def deco(fn):
            self.routes[("POST", path)] = fn
            return fn

        return deco


class Phase1ProofCycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / "fabos.db")
        self.db.initialize()
        migrate(self.db)
        self.vault = DesignVaultService(self.db, self.temp.name)
        self.proofs = DesignProofService(self.db, self.vault)
        self.settings = ShopSettingsService(self.db)
        with self.db.connect() as conn:
            conn.execute(
                "INSERT INTO users(id,username,password_hash,role,active,account_type) VALUES(?,?,?,?,?,?)",
                ("customer-user", "customer", "unused", "customer", 1, "customer"),
            )
            conn.execute(
                "INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                ("customer-1", "Test Customer", "customer@example.com"),
            )
            conn.execute(
                "INSERT INTO customer_accounts(user_id,customer_id) VALUES(?,?)",
                ("customer-user", "customer-1"),
            )
            for n in ("1", "2"):
                conn.execute(
                    "INSERT INTO quotes(id,quote_number,customer_id,status,total_cents) VALUES(?,?,?,?,?)",
                    ("quote-%s" % n, "Q-TEST-000%s" % n, "customer-1", "accepted", 4200),
                )
                conn.execute(
                    "INSERT INTO designs(id,product_id,name,current_version) VALUES(?,?,?,?)",
                    ("design-%s" % n, None, "Customer Part %s" % n, 1),
                )
                conn.execute(
                    "INSERT INTO design_versions(id,design_id,version,label) VALUES(?,?,?,?)",
                    ("design-version-%s" % n, "design-%s" % n, 1, "Customer upload"),
                )
                conn.execute(
                    "INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)",
                    ("quote-%s" % n, "design-%s" % n),
                )
            conn.commit()

    def tearDown(self):
        self.temp.cleanup()

    # -- 1. expires_at in the customer quote payload -------------------------

    def test_fastapi_quote_payload_includes_expires_at(self):
        value = _quote_payload({
            "id": "q1", "quote_number": "Q-1", "status": "sent",
            "notes": "", "created_at": "2026-10-01", "updated_at": "2026-10-02",
            "total_cents": 5000, "expires_at": "2026-10-15",
        })
        self.assertEqual(value["expires_at"], "2026-10-15")

    def test_fastapi_quote_payload_omits_expires_at_when_unset(self):
        value = _quote_payload({"id": "q1", "quote_number": "Q-1", "status": "draft"})
        self.assertNotIn("expires_at", value)

    def test_public_quote_projection_includes_expires_at(self):
        value = _public_quote({
            "id": "q1", "quote_number": "Q-1", "status": "sent",
            "total_cents": 5000, "expires_at": "2026-10-15",
        })
        self.assertEqual(value["expires_at"], "2026-10-15")

    def test_order_payload_includes_quote_id(self):
        value = _order_payload({
            "id": "o1", "order_number": "O-1", "status": "confirmed",
            "total_cents": 5000, "quote_id": "quote-9",
        })
        self.assertEqual(value["quote_id"], "quote-9")

    def test_order_payload_omits_quote_id_when_unset(self):
        value = _order_payload({"id": "o1", "order_number": "O-1", "status": "confirmed"})
        self.assertNotIn("quote_id", value)

    # -- 2. quote_validity_days setting ---------------------------------------

    def test_quote_validity_days_defaults_to_14(self):
        self.assertEqual(self.settings.quote_validity_days(), 14)

    def test_quote_validity_days_is_configurable(self):
        self.settings.set_validated("quote_validity_days", "30")
        self.assertEqual(self.settings.quote_validity_days(), 30)

    def test_quote_validity_days_rejects_garbage_and_non_positive(self):
        self.settings.set_validated("quote_validity_days", "7")
        with self.db.connect() as conn:
            conn.execute("UPDATE shop_settings SET value='not-a-number' WHERE key='quote_validity_days'")
            conn.commit()
        self.assertEqual(self.settings.quote_validity_days(), 14)
        with self.db.connect() as conn:
            conn.execute("UPDATE shop_settings SET value='0' WHERE key='quote_validity_days'")
            conn.commit()
        self.assertEqual(self.settings.quote_validity_days(), 14)

    def test_quote_validity_days_has_metadata_and_validation(self):
        self.assertIn("quote_validity_days", ShopSettingsService.NUMERIC_KEYS)
        self.assertIn("quote_validity_days", ShopSettingsService.META["sales"])
        self.assertEqual(
            ShopSettingsService.META["sales"]["quote_validity_days"],
            "Quote validity period",
        )
        with self.assertRaises(ValueError):
            self.settings.set_validated("quote_validity_days", "-3")
        with self.assertRaises(ValueError):
            self.settings.set_validated("quote_validity_days", "soon")
        # The setting appears in the settings snapshot surfaced to the admin UI.
        self.assertIn("quote_validity_days", self.settings.snapshot())

    def test_quote_validity_days_drives_expiry_computation(self):
        # Pin the expiry formula used by the admin send path, checkout, and
        # the WSGI mirror: today + the configured validity window.
        self.settings.set_validated("quote_validity_days", "21")
        expected = (date.today() + timedelta(days=self.settings.quote_validity_days())).isoformat()
        self.assertEqual(expected, (date.today() + timedelta(days=21)).isoformat())

    def test_no_hardcoded_14_day_quote_expiry_remains(self):
        for path in (
            "fabos_core/api.py",
            "fabos_core/services/checkout.py",
            "fabos_api/wsgi_extended.py",
        ):
            source = Path(path).read_text(encoding="utf-8")
            self.assertNotIn(
                "timedelta(days=14)", source,
                "hardcoded 14-day quote expiry still present in %s" % path,
            )

    def test_migration_renames_legacy_setting(self):
        # Simulate an older database that still carries the legacy key:
        # remove the new key, plant the legacy one, then run the same
        # rename logic migration 50 applies.
        with self.db.connect() as conn:
            conn.execute("DELETE FROM shop_settings WHERE key='quote_validity_days'")
            conn.execute("INSERT OR IGNORE INTO shop_settings(key,value) VALUES('quote_valid_days','21')")
            conn.commit()
        self.assertEqual(self.settings.quote_validity_days(), 14)  # default, new key absent
        with self.db.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO shop_settings(key,value)
                   SELECT 'quote_validity_days',COALESCE(
                     (SELECT value FROM shop_settings WHERE key='quote_valid_days'),'14')"""
            )
            conn.execute("DELETE FROM shop_settings WHERE key='quote_valid_days'")
            conn.commit()
        self.assertEqual(self.settings.quote_validity_days(), 21)
        with self.db.connect() as conn:
            legacy = conn.execute(
                "SELECT value FROM shop_settings WHERE key='quote_valid_days'"
            ).fetchone()
        self.assertIsNone(legacy)

    # -- 3. changes_requested notification hook -------------------------------

    def test_changes_requested_fires_notification_hook(self):
        proof = self.proofs.create("quote-1", status="sent")
        with patch.object(
            notifications, "notify_proof_changes_requested", autospec=True
        ) as hook:
            changed = self.proofs.request_changes("customer-user", proof["id"], "Make it taller.")
        self.assertEqual(changed["status"], "changes_requested")
        hook.assert_called_once()
        (fired_proof,), _ = hook.call_args
        self.assertEqual(fired_proof["id"], proof["id"])
        self.assertEqual(fired_proof["status"], "changes_requested")
        self.assertEqual(fired_proof["customer_comment"], "Make it taller.")

    def test_approve_does_not_fire_notification_hook(self):
        proof = self.proofs.create("quote-1", status="sent")
        with patch.object(
            notifications, "notify_proof_changes_requested", autospec=True
        ) as hook:
            approved = self.proofs.approve("customer-user", proof["id"], "Looks good.")
        self.assertEqual(approved["status"], "approved")
        hook.assert_not_called()

    def test_changes_requested_hook_notifies_the_customer(self):
        # Phase 2: the changes_requested hook now produces a real customer
        # notification record (change-request receipt) instead of a log line.
        proof = self.proofs.create("quote-1", status="sent")
        self.proofs.request_changes("customer-user", proof["id"], "Make it taller.")
        with self.db.connect() as conn:
            rows = [dict(r) for r in conn.execute(
                "SELECT event_type,deep_link,body FROM customer_notifications "
                "WHERE customer_id='customer-1' ORDER BY created_at").fetchall()]
        events = [r["event_type"] for r in rows]
        self.assertIn("proof_sent", events)
        self.assertIn("proof_changes_requested", events)
        changes = [r for r in rows if r["event_type"] == "proof_changes_requested"][0]
        self.assertEqual(changes["deep_link"], "/quote.html?id=quote-1#proof")
        self.assertIn("Make it taller.", changes["body"])

    def test_notify_hook_returns_a_receipt(self):
        receipt = notifications.notify_proof_changes_requested(
            {"id": "p1", "quote_id": "q1", "quote_number": "Q-1",
             "design_version": 2, "customer_comment": "Taller please."}
        )
        self.assertTrue(receipt["notified"])
        self.assertEqual(receipt["channel"], "log")
        self.assertEqual(receipt["proof_id"], "p1")

    # -- 4. admin proof endpoints ---------------------------------------------

    def _registered_admin_proof_routes(self):
        app = _FakeApp()
        register_design_proof_routes(
            app,
            get_application=lambda: None,
            customer_user=lambda: None,
            administrator_user=lambda: None,
        )
        return app.routes

    def _seed_two_proofs(self):
        proof1 = self.proofs.create("quote-1", notes="v1 staff note", status="sent")
        self.proofs.request_changes("customer-user", proof1["id"], "Please make it taller.")
        proof2 = self.proofs.create("quote-2", notes="quote-2 note", status="sent")
        return proof1, proof2

    def test_fastapi_admin_proofs_list_filterable_by_status(self):
        proof1, proof2 = self._seed_two_proofs()
        routes = self._registered_admin_proof_routes()
        application = SimpleNamespace(design_proofs=self.proofs)
        endpoint = routes[("GET", "/api/v1/admin/proofs")]

        changes = endpoint(status="changes_requested", application=application)
        self.assertEqual([p["id"] for p in changes["proofs"]], [proof1["id"]])
        sent = endpoint(status="sent", application=application)
        self.assertEqual([p["id"] for p in sent["proofs"]], [proof2["id"]])
        all_proofs = endpoint(application=application)
        self.assertEqual(len(all_proofs["proofs"]), 2)

    def test_fastapi_admin_proofs_list_rejects_unknown_status(self):
        routes = self._registered_admin_proof_routes()
        application = SimpleNamespace(design_proofs=self.proofs)
        endpoint = routes[("GET", "/api/v1/admin/proofs")]
        with self.assertRaises(HTTPException) as ctx:
            endpoint(status="bogus", application=application)
        self.assertEqual(ctx.exception.status_code, 400)

    def test_fastapi_admin_proof_detail_includes_comment_and_staff_note(self):
        proof1, _ = self._seed_two_proofs()
        routes = self._registered_admin_proof_routes()
        application = SimpleNamespace(design_proofs=self.proofs)
        endpoint = routes[("GET", "/api/v1/admin/proofs/{proof_id}")]

        payload = endpoint(proof_id=proof1["id"], application=application)
        self.assertEqual(payload["proof"]["id"], proof1["id"])
        self.assertEqual(payload["proof"]["customer_comment"], "Please make it taller.")
        self.assertEqual(payload["proof"]["notes"], "v1 staff note")

        with self.assertRaises(HTTPException) as ctx:
            endpoint(proof_id="no-such-proof", application=application)
        self.assertEqual(ctx.exception.status_code, 404)

    def test_fastapi_admin_quote_proofs_list_accepts_status_filter(self):
        proof1, _ = self._seed_two_proofs()
        routes = self._registered_admin_proof_routes()
        application = SimpleNamespace(design_proofs=self.proofs)
        endpoint = routes[("GET", "/api/v1/admin/quotes/{quote_id}/proofs")]

        filtered = endpoint(quote_id="quote-1", status="changes_requested", application=application)
        self.assertEqual([p["id"] for p in filtered["proofs"]], [proof1["id"]])
        empty = endpoint(quote_id="quote-1", status="approved", application=application)
        self.assertEqual(empty["proofs"], [])

    def test_wsgi_admin_proofs_queue_parity(self):
        proof1, proof2 = self._seed_two_proofs()
        core = SimpleNamespace(
            security=_Security(), design_proofs=self.proofs,
            design_vault=SimpleNamespace(root=self.temp.name), error_log=_Log(),
        )
        api = FabOSAPI(core)
        admin = {"Authorization": "Bearer admin-token"}

        filtered = api.request("GET", "/api/v1/admin/proofs?status=changes_requested", headers=admin)
        self.assertEqual(filtered["status"], 200)
        self.assertEqual([p["id"] for p in filtered["data"]["proofs"]], [proof1["id"]])

        everything = api.request("GET", "/api/v1/admin/proofs", headers=admin)
        self.assertEqual(everything["status"], 200)
        self.assertEqual(len(everything["data"]["proofs"]), 2)

        bad = api.request("GET", "/api/v1/admin/proofs?status=bogus", headers=admin)
        self.assertEqual(bad["status"], 400)

        detail = api.request("GET", "/api/v1/admin/proofs/%s" % proof2["id"], headers=admin)
        self.assertEqual(detail["status"], 200)
        self.assertEqual(detail["data"]["proof"]["customer_comment"], "")
        self.assertEqual(detail["data"]["proof"]["notes"], "quote-2 note")

        missing = api.request("GET", "/api/v1/admin/proofs/no-such-proof", headers=admin)
        self.assertEqual(missing["status"], 404)

        per_quote = api.request(
            "GET", "/api/v1/admin/quotes/quote-1/proofs?status=changes_requested", headers=admin
        )
        self.assertEqual(per_quote["status"], 200)
        self.assertEqual([p["id"] for p in per_quote["data"]["proofs"]], [proof1["id"]])

    def test_wsgi_admin_proofs_require_admin(self):
        proof1, _ = self._seed_two_proofs()
        core = SimpleNamespace(
            security=_Security(), design_proofs=self.proofs,
            design_vault=SimpleNamespace(root=self.temp.name), error_log=_Log(),
        )
        api = FabOSAPI(core)
        denied = api.request("GET", "/api/v1/admin/proofs")
        self.assertIn(denied["status"], (401, 403))
        detail = api.request("GET", "/api/v1/admin/proofs/%s" % proof1["id"])
        self.assertIn(detail["status"], (401, 403))

    # -- 5. per-revision staff note -------------------------------------------

    def test_staff_note_stored_per_revision_and_returned_to_admin(self):
        proof = self.proofs.create("quote-1", notes="v1: check the hole diameter", status="draft")
        self.assertEqual(self.proofs._admin(proof)["notes"], "v1: check the hole diameter")
        sent = self.proofs.send(proof["id"], notes="v2: resized per customer request")
        self.assertEqual(self.proofs._admin(sent)["notes"], "v2: resized per customer request")
        listed = self.proofs.list_for_admin(quote_id="quote-1")
        self.assertEqual(listed[0]["notes"], "v2: resized per customer request")

    def test_staff_note_never_leaks_to_customer_projection(self):
        proof = self.proofs.create("quote-1", notes="internal margin discussion", status="sent")
        public = self.proofs._public(proof)
        self.assertNotIn("notes", public)
        listed = self.proofs.list_for_customer("customer-user")
        self.assertTrue(all("notes" not in item for item in listed))

    def test_customer_note_defaults_to_empty_string(self):
        proof = self.proofs.create("quote-1", status="sent")
        self.assertEqual(self.proofs._public(proof)["customer_note"], "")

    def test_customer_note_set_at_create_and_visible_to_customer(self):
        proof = self.proofs.create(
            "quote-1", notes="internal: check margins", customer_note="v1: first look at the bracket",
            status="sent",
        )
        public = self.proofs._public(proof)
        self.assertEqual(public["customer_note"], "v1: first look at the bracket")
        self.assertNotIn("notes", public)
        admin = self.proofs._admin(proof)
        self.assertEqual(admin["customer_note"], "v1: first look at the bracket")
        self.assertEqual(admin["notes"], "internal: check margins")

    def test_customer_note_writable_at_send_time(self):
        proof = self.proofs.create("quote-1", notes="internal", status="draft")
        sent = self.proofs.send(proof["id"], customer_note="v2: resized per your request")
        self.assertEqual(sent["customer_note"], "v2: resized per your request")
        # Internal notes are preserved when only the customer note is updated.
        self.assertEqual(sent["notes"], "internal")
        customer_view = self.proofs.get_for_customer("customer-user", proof["id"])
        self.assertEqual(customer_view["customer_note"], "v2: resized per your request")
        self.assertNotIn("notes", customer_view)

    def test_migration_adds_customer_note_column(self):
        with self.db.connect() as conn:
            columns = [row[1] for row in conn.execute("PRAGMA table_info(design_proofs)")]
        self.assertIn("customer_note", columns)

    def test_fastapi_create_and_send_routes_accept_customer_note(self):
        routes = self._registered_admin_proof_routes()
        application = SimpleNamespace(design_proofs=self.proofs)

        create = routes[("POST", "/api/v1/admin/quotes/{quote_id}/proofs")]
        payload = create(
            quote_id="quote-1",
            payload=ProofCreateRequest(notes="internal", customer_note="v1 note", send=False),
            application=application,
        )
        proof_id = payload["proof"]["id"]
        self.assertEqual(payload["proof"]["customer_note"], "v1 note")
        self.assertEqual(payload["proof"]["notes"], "internal")

        send = routes[("POST", "/api/v1/admin/proofs/{proof_id}/send")]
        sent = send(
            proof_id=proof_id,
            payload=ProofComment(comment="", customer_note="v2 customer note"),
            application=application,
        )
        self.assertEqual(sent["proof"]["customer_note"], "v2 customer note")
        self.assertEqual(sent["proof"]["notes"], "internal")
        customer_view = self.proofs.get_for_customer("customer-user", proof_id)
        self.assertEqual(customer_view["customer_note"], "v2 customer note")
        self.assertNotIn("notes", customer_view)

    def test_wsgi_send_route_accepts_customer_note(self):
        proof = self.proofs.create("quote-1", notes="internal", status="draft")
        core = SimpleNamespace(
            security=_Security(), design_proofs=self.proofs,
            design_vault=SimpleNamespace(root=self.temp.name), error_log=_Log(),
        )
        api = FabOSAPI(core)
        admin = {"Authorization": "Bearer admin-token"}

        response = api.request(
            "POST", "/api/v1/admin/proofs/%s/send" % proof["id"],
            {"customer_note": "v2: taller bracket as requested"}, admin,
        )
        self.assertEqual(response["status"], 200)
        self.assertEqual(response["data"]["proof"]["customer_note"], "v2: taller bracket as requested")
        self.assertEqual(response["data"]["proof"]["notes"], "internal")

        customer_view = self.proofs.get_for_customer("customer-user", proof["id"])
        self.assertEqual(customer_view["customer_note"], "v2: taller bracket as requested")
        self.assertNotIn("notes", customer_view)

    # -- 6. AI-draft seam -----------------------------------------------------

    def test_draft_proof_message_is_an_unimplemented_seam(self):
        with self.assertRaises(NotImplementedError):
            notifications.draft_proof_message({"id": "p1"}, purpose="proof_sent")


if __name__ == "__main__":
    logging.basicConfig(level=logging.CRITICAL)
    unittest.main()
