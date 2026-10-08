"""Phase 4 + Phase 5 regression tests: tracking/fulfillment + attention system.

Phase 4 (backend):
- Customer order payload carries a `fulfillment` object with all ten keys,
  null (never omitted) for unknown values; tracking_url derived from known
  carriers; estimated_delivery sketched from shipped_at + carrier transit.
- PATCH /api/v1/admin/fulfillments/{id} edits method/carrier/tracking/
  destination (admin-gated, 404 for unknown id, 400 for bad input).
- POST /api/v1/admin/fulfillments/{id}/transition enforces the state machine:
  packed -> shipped -> delivered, ready_for_pickup -> picked_up,
  packed -> ready_for_pickup; skipping steps rejected with 400.
- packed_at is recorded; shipped transition fires the Phase 2 order_shipped
  customer notification (with carrier + tracking).
- Fulfillment auto-creation derives the method from the order's shipping
  data instead of defaulting to pickup; ready_for_pickup auto-flip stays
  pickup-only.

Phase 5 (backend):
- action_items() gains "Quote needs pricing" (draft/under_review, high after
  24h) and "Order accepted - production not started" (pending/confirmed with
  no active jobs, high after 48h), each with page/id deep links.
- Existing "Quote awaiting approval" escalates to high after 7 days.
- GET /api/v1/admin/operations/dashboard accepts ?all=true / ?limit=N;
  default behavior (cap 20) unchanged.
"""
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI
from fabos_core.api import create_app
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.fulfillment import FulfillmentService
from fabos_core.services.operations_hub import OperationsHubService


FULFILLMENT_KEYS = ("carrier", "tracking_number", "tracking_url", "method",
                    "status", "packed_at", "shipped_at", "delivered_at",
                    "picked_up_at", "estimated_delivery")


class _Accounts:
    def __init__(self, account_type="administrator"):
        self.account_type = account_type

    def get_user(self, user_id):
        return {"id": user_id, "active": 1, "account_type": self.account_type}

    def customer_for_user(self, user_id):
        return None


class _Permissions:
    def require(self, account_type, permission, user_id=None):
        return True

    def has_permission(self, account_type, permission, user_id=None):
        return True


class _Db:
    def __init__(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name) / "fabos.sqlite3")
        self.db.initialize()
        migrate(self.db)

    def close(self):
        self.tmp.cleanup()


def _service(db):
    return FulfillmentService(db, _Accounts(), _Permissions())


def _ready_order(db, number="O-P4", **kwargs):
    oid = str(uuid.uuid4())
    cols = {"id": oid, "order_number": number, "status": "ready", "total_cents": 0}
    cols.update(kwargs)
    with db.connect() as c:
        c.execute(
            "INSERT INTO orders(id,order_number,status,total_cents,shipping_cents,"
            "shipping_address_json,customer_id) VALUES(?,?,?,?,?,?,?)",
            (cols["id"], cols["order_number"], cols["status"], cols["total_cents"],
             cols.get("shipping_cents", 0), cols.get("shipping_address_json", "{}"),
             cols.get("customer_id")))
        c.commit()
    return oid


class FulfillmentPayloadTests(unittest.TestCase):
    def test_empty_payload_has_all_keys_as_null(self):
        payload = FulfillmentService.customer_payload(None)
        self.assertEqual(tuple(sorted(payload.keys())), tuple(sorted(FULFILLMENT_KEYS)))
        self.assertTrue(all(v is None for v in payload.values()))

    def test_tracking_url_derivation(self):
        cases = [
            ("UPS", "1Z999", "https://www.ups.com/track?tracknum=1Z999"),
            ("ups ground", "1Z999", "https://www.ups.com/track?tracknum=1Z999"),
            ("FedEx", "1234", "https://www.fedex.com/fedextrack/?trknbr=1234"),
            ("USPS", "9400", "https://tools.usps.com/go/TrackConfirmAction?tLabels=9400"),
            ("DHL Express", "5678",
             "https://www.dhl.com/us-en/home/tracking/tracking-express.html?submit=1&tracking-id=5678"),
            ("Some Local Courier", "ABC", None),
            ("UPS", "", None),
            ("", "1Z999", None),
        ]
        for carrier, number, expected in cases:
            with self.subTest(carrier=carrier):
                payload = FulfillmentService.customer_payload(
                    {"carrier": carrier, "tracking_number": number,
                     "method": "shipping", "status": "shipped"})
                self.assertEqual(payload["tracking_url"], expected)
                self.assertEqual(payload["carrier"] or None, carrier or None)
                self.assertEqual(payload["tracking_number"] or None, number or None)

    def test_estimated_delivery_sketch(self):
        shipped = "2026-10-01T10:00:00"
        payload = FulfillmentService.customer_payload(
            {"carrier": "UPS", "tracking_number": "1Z", "method": "shipping",
             "status": "shipped", "shipped_at": shipped})
        self.assertEqual(payload["estimated_delivery"], "2026-10-06")
        # Delivered orders have no estimate; unknown carriers fall back to 5d.
        payload = FulfillmentService.customer_payload(
            {"carrier": "UPS", "shipped_at": shipped, "delivered_at": "2026-10-03T10:00:00",
             "method": "shipping", "status": "delivered"})
        self.assertIsNone(payload["estimated_delivery"])
        payload = FulfillmentService.customer_payload(
            {"carrier": "Mystery", "shipped_at": shipped, "method": "shipping", "status": "shipped"})
        self.assertEqual(payload["estimated_delivery"], "2026-10-06")
        payload = FulfillmentService.customer_payload({"method": "pickup", "status": "pending"})
        self.assertIsNone(payload["estimated_delivery"])


class FulfillmentMethodDerivationTests(unittest.TestCase):
    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db

    def test_paid_shipping_derives_shipping(self):
        oid = _ready_order(self.db, "O-SHIP1", shipping_cents=600,
                           shipping_address_json='{"address":"1 Main St"}')
        self.assertEqual(_service(self.db).derive_method(oid), "shipping")

    def test_address_only_derives_shipping(self):
        oid = _ready_order(self.db, "O-SHIP2",
                           shipping_address_json='{"address":"1 Main St","city":"Auxvasse"}')
        self.assertEqual(_service(self.db).derive_method(oid), "shipping")

    def test_bare_order_derives_pickup(self):
        oid = _ready_order(self.db, "O-PICK")
        self.assertEqual(_service(self.db).derive_method(oid), "pickup")

    def test_ensure_defaults_to_derived_method(self):
        ship = _ready_order(self.db, "O-SHIP3", shipping_cents=100)
        pick = _ready_order(self.db, "O-PICK3")
        service = _service(self.db)
        with self.db.connect() as c:
            service.ensure(ship)
            service.ensure(pick)
            methods = {r["order_id"]: r["method"]
                       for r in c.execute("SELECT order_id,method FROM fulfillments").fetchall()}
        self.assertEqual(methods[ship], "shipping")
        self.assertEqual(methods[pick], "pickup")

    def test_reconcile_derives_method_and_keeps_pickup_autoflip(self):
        ship = _ready_order(self.db, "O-SHIP4", shipping_cents=250)
        pick = _ready_order(self.db, "O-PICK4")
        hub = OperationsHubService(SimpleNamespace(database=self.db, shop_settings={}))
        hub.reconcile_workflows()
        with self.db.connect() as c:
            rows = {r["order_id"]: dict(r) for r in
                    c.execute("SELECT order_id,method,status FROM fulfillments").fetchall()}
        self.assertEqual(rows[ship]["method"], "shipping")
        self.assertEqual(rows[ship]["status"], "pending")
        self.assertEqual(rows[pick]["method"], "pickup")
        self.assertEqual(rows[pick]["status"], "ready_for_pickup")


class FulfillmentTransitionTests(unittest.TestCase):
    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db
        self.service = _service(self.db)
        self.admin = "admin-1"

    def _shipping_packed(self, number="O-TR"):
        oid = _ready_order(self.db, number, shipping_cents=500,
                           shipping_address_json='{"address":"1 Main"}')
        fid = self.service.ensure(oid, "shipping")
        self.service.save(oid, "shipping", "packed")
        return oid, fid

    def _status(self, fid):
        with self.db.connect() as c:
            return c.execute(
                "SELECT status,method,packed_at,shipped_at FROM fulfillments WHERE id=?",
                (fid,)).fetchone()

    def test_valid_chain_packed_shipped_delivered(self):
        _oid, fid = self._shipping_packed()
        self.service.transition_for_user(self.admin, fid, "shipped")
        row = self._status(fid)
        self.assertEqual(row["status"], "shipped")
        self.assertIsNotNone(row["shipped_at"])
        self.service.transition_for_user(self.admin, fid, "delivered")
        self.assertEqual(self._status(fid)["status"], "delivered")

    def test_packed_at_recorded(self):
        _oid, fid = self._shipping_packed()
        self.assertIsNotNone(self._status(fid)["packed_at"])

    def test_skip_step_rejected(self):
        _oid, fid = self._shipping_packed()
        with self.assertRaisesRegex(ValueError, "Cannot transition.*packed.*delivered"):
            self.service.transition_for_user(self.admin, fid, "delivered")
        self.assertEqual(self._status(fid)["status"], "packed")

    def test_unknown_state_rejected(self):
        _oid, fid = self._shipping_packed()
        with self.assertRaisesRegex(ValueError, "Unknown fulfillment status"):
            self.service.transition_for_user(self.admin, fid, "teleported")

    def test_unknown_id_raises_keyerror(self):
        with self.assertRaises(KeyError):
            self.service.transition_for_user(self.admin, "nope", "shipped")

    def test_same_state_rejected(self):
        _oid, fid = self._shipping_packed()
        with self.assertRaisesRegex(ValueError, "already 'packed'"):
            self.service.transition_for_user(self.admin, fid, "packed")

    def test_pickup_flow_ready_for_pickup_to_picked_up(self):
        oid = _ready_order(self.db, "O-PU")
        fid = self.service.ensure(oid, "pickup")
        self.service.transition_for_user(self.admin, fid, "ready_for_pickup")
        self.assertEqual(self._status(fid)["status"], "ready_for_pickup")
        self.service.transition_for_user(self.admin, fid, "picked_up")
        self.assertEqual(self._status(fid)["status"], "picked_up")

    def test_pickup_cannot_use_shipping_states(self):
        # pending -> ready_for_pickup is a legal edge, but a shipping-method
        # fulfillment may not take a pickup-only state.
        oid = _ready_order(self.db, "O-PU2", shipping_cents=100,
                           shipping_address_json='{"address":"1 Main"}')
        fid = self.service.ensure(oid, "shipping")
        with self.assertRaisesRegex(ValueError, "shipping fulfillment"):
            self.service.transition_for_user(self.admin, fid, "ready_for_pickup")
        self.assertEqual(self._status(fid)["status"], "pending")

    def test_packed_to_ready_for_pickup_flips_method(self):
        _oid, fid = self._shipping_packed("O-CONV")
        result = self.service.transition_for_user(self.admin, fid, "ready_for_pickup")
        self.assertEqual(result["status"], "ready_for_pickup")
        self.assertEqual(result["method"], "pickup")

    def test_terminal_is_final(self):
        _oid, fid = self._shipping_packed("O-TERM")
        self.service.transition_for_user(self.admin, fid, "shipped")
        self.service.transition_for_user(self.admin, fid, "delivered")
        with self.assertRaisesRegex(ValueError, "Valid next states: none"):
            self.service.transition_for_user(self.admin, fid, "shipped")

    def test_shipped_transition_fires_order_shipped_notification(self):
        cid = str(uuid.uuid4())
        with self.db.connect() as c:
            c.execute("INSERT INTO customers(id,name,email) VALUES(?,?,?)",
                      (cid, "T. Customer", "t@example.com"))
            c.commit()
        oid = _ready_order(self.db, "O-NOTIF", shipping_cents=500,
                           shipping_address_json='{"address":"1 Main"}',
                           customer_id=cid)
        fid = self.service.ensure(oid, "shipping")
        self.service.update_for_user(self.admin, fid, carrier="UPS", tracking_number="1Z999")
        self.service.transition_for_user(self.admin, fid, "packed")
        self.service.transition_for_user(self.admin, fid, "shipped")
        with self.db.connect() as c:
            row = c.execute(
                "SELECT event_type,title,body FROM customer_notifications WHERE dedupe_key=?",
                ("order_shipped:%s" % fid,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["event_type"], "order_shipped")
        self.assertIn("UPS", row["body"])
        self.assertIn("1Z999", row["body"])


class FulfillmentUpdateTests(unittest.TestCase):
    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db
        self.service = _service(self.db)
        self.admin = "admin-1"

    def test_update_edits_fields(self):
        oid = _ready_order(self.db, "O-UPD", shipping_cents=100)
        fid = self.service.ensure(oid, "shipping")
        result = self.service.update_for_user(
            self.admin, fid, carrier="FedEx", tracking_number="FX1", destination="90210")
        self.assertEqual(result["carrier"], "FedEx")
        self.assertEqual(result["tracking_number"], "FX1")
        self.assertEqual(result["destination"], "90210")
        self.assertEqual(result["method"], "shipping")

    def test_update_method_while_pending(self):
        oid = _ready_order(self.db, "O-UPD2")
        fid = self.service.ensure(oid, "pickup")
        result = self.service.update_for_user(self.admin, fid, method="shipping")
        self.assertEqual(result["method"], "shipping")

    def test_update_rejects_bad_method(self):
        oid = _ready_order(self.db, "O-UPD3")
        fid = self.service.ensure(oid, "pickup")
        with self.assertRaisesRegex(ValueError, "Unsupported fulfillment method"):
            self.service.update_for_user(self.admin, fid, method="drone")

    def test_update_rejects_method_change_after_start(self):
        oid = _ready_order(self.db, "O-UPD4", shipping_cents=100)
        fid = self.service.ensure(oid, "shipping")
        self.service.save(oid, "shipping", "packed")
        # A packed (shipping-only) fulfillment cannot flip to pickup while it
        # is still packed; the sanctioned path is the packed->ready_for_pickup
        # transition, which flips the method as part of the move.
        with self.assertRaisesRegex(ValueError, "cannot use shipping-only status"):
            self.service.update_for_user(self.admin, fid, method="pickup")
        result = self.service.transition_for_user(self.admin, fid, "ready_for_pickup")
        self.assertEqual(result["method"], "pickup")

    def test_update_unknown_id(self):
        with self.assertRaises(KeyError):
            self.service.update_for_user(self.admin, "nope", carrier="UPS")

    def test_non_admin_denied(self):
        staff_service = FulfillmentService(self.db, _Accounts("customer"), _Permissions())
        # customer_for_user returns None -> PermissionError from _require path;
        # use a stub that passes _user but fails the permission check instead.
        class _Deny(_Permissions):
            def require(self, account_type, permission, user_id=None):
                raise PermissionError("denied")
        denied = FulfillmentService(self.db, _Accounts("employee"), _Deny())
        oid = _ready_order(self.db, "O-UPD5")
        fid = self.service.ensure(oid, "pickup")
        with self.assertRaises(PermissionError):
            denied.update_for_user("emp-1", fid, carrier="UPS")
        with self.assertRaises(PermissionError):
            denied.transition_for_user("emp-1", fid, "ready_for_pickup")
        self.assertIsNotNone(staff_service)  # silence unused


class FulfillmentRouteTests(unittest.TestCase):
    """PATCH / transition endpoints on both transports."""

    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db
        self.service = _service(self.db)
        self.oid = _ready_order(self.db, "O-RTE", shipping_cents=300,
                                shipping_address_json='{"address":"1 Main"}')
        self.fid = self.service.ensure(self.oid, "shipping")

    def _fastapi(self, account_type="administrator"):
        core = SimpleNamespace(database=self.db, fulfillment=self.service)
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "u1", "account_type": account_type, "role": "owner"}
        return TestClient(app)

    def _wsgi(self, account_type="administrator"):
        core = SimpleNamespace(
            database=self.db,
            fulfillment=self.service,
            shop_settings={},
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": "u1", "account_type": account_type}),
            accounts=SimpleNamespace(get_user=lambda uid: {"id": uid, "role": "owner"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        return FabOSAPI(core), {"Authorization": "Bearer <redacted>"}

    def test_fastapi_patch_and_transition(self):
        client = self._fastapi()
        response = client.patch("/api/v1/admin/fulfillments/%s" % self.fid,
                                json={"carrier": "UPS", "tracking_number": "1Z1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fulfillment"]["carrier"], "UPS")
        response = client.post("/api/v1/admin/fulfillments/%s/transition" % self.fid,
                               json={"to_state": "packed"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["fulfillment"]["status"], "packed")
        self.assertIsNotNone(response.json()["fulfillment"]["packed_at"])
        # Skipping packed -> delivered is a 400.
        response = client.post("/api/v1/admin/fulfillments/%s/transition" % self.fid,
                               json={"to_state": "delivered"})
        self.assertEqual(response.status_code, 400)
        self.assertIn("Cannot transition", response.json()["detail"])
        # Unknown id is a 404.
        response = client.patch("/api/v1/admin/fulfillments/nope", json={"carrier": "UPS"})
        self.assertEqual(response.status_code, 404)
        response = client.post("/api/v1/admin/fulfillments/nope/transition",
                               json={"to_state": "shipped"})
        self.assertEqual(response.status_code, 404)
        # Non-admin is a 403.
        response = self._fastapi("customer").patch(
            "/api/v1/admin/fulfillments/%s" % self.fid, json={"carrier": "UPS"})
        self.assertEqual(response.status_code, 403)

    def test_wsgi_patch_and_transition(self):
        api, headers = self._wsgi()
        result = api.request("PATCH", "/api/v1/admin/fulfillments/%s" % self.fid,
                             {"carrier": "USPS", "tracking_number": "9400"}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["fulfillment"]["carrier"], "USPS")
        result = api.request("POST", "/api/v1/admin/fulfillments/%s/transition" % self.fid,
                             {"to_state": "packed"}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["fulfillment"]["status"], "packed")
        result = api.request("POST", "/api/v1/admin/fulfillments/%s/transition" % self.fid,
                             {"to_state": "delivered"}, headers)
        self.assertEqual(result["status"], 400)
        result = api.request("PATCH", "/api/v1/admin/fulfillments/nope",
                             {"carrier": "UPS"}, headers)
        self.assertEqual(result["status"], 404)
        result = api.request("POST", "/api/v1/admin/fulfillments/%s/transition" % self.fid,
                             {}, headers)
        self.assertEqual(result["status"], 400)
        api2, headers2 = self._wsgi("customer")
        result = api2.request("PATCH", "/api/v1/admin/fulfillments/%s" % self.fid,
                              {"carrier": "UPS"}, headers2)
        self.assertEqual(result["status"], 403)

    def test_wsgi_customer_order_carries_fulfillment_payload(self):
        self.service.save(self.oid, "shipping", "packed")
        self.service.update_for_user("u1", self.fid, carrier="UPS", tracking_number="1Z1")
        self.service.transition_for_user("u1", self.fid, "shipped")
        core_orders = SimpleNamespace(
            get_for_user=lambda uid, oid: ({"id": self.oid, "order_number": "O-RTE",
                                            "status": "shipped", "total_cents": 100}, []),
            dossier=lambda oid: {"next_step": None, "designs": []},
        )
        api, headers = self._wsgi()
        api.core.orders = core_orders
        result = api.request("GET", "/api/v1/customer/orders/%s" % self.oid, {}, headers)
        self.assertEqual(result["status"], 200)
        fulfillment = result["data"]["order"]["fulfillment"]
        self.assertEqual(tuple(sorted(fulfillment.keys())), tuple(sorted(FULFILLMENT_KEYS)))
        self.assertEqual(fulfillment["carrier"], "UPS")
        self.assertEqual(fulfillment["tracking_number"], "1Z1")
        self.assertEqual(fulfillment["tracking_url"],
                         "https://www.ups.com/track?tracknum=1Z1")
        self.assertEqual(fulfillment["method"], "shipping")
        self.assertEqual(fulfillment["status"], "shipped")
        self.assertIsNotNone(fulfillment["shipped_at"])
        self.assertIsNotNone(fulfillment["estimated_delivery"])

    def test_fastapi_customer_order_carries_fulfillment_payload(self):
        self.service.save(self.oid, "shipping", "packed")
        core = SimpleNamespace(
            database=self.db,
            fulfillment=self.service,
            orders=SimpleNamespace(
                get_for_user=lambda uid, oid: ({"id": self.oid, "order_number": "O-RTE",
                                                "status": "shipped", "total_cents": 100}, []),
                dossier=lambda oid: {"next_step": None, "designs": []},
            ),
        )
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "u1", "account_type": "customer", "role": ""}
        client = TestClient(app)
        response = client.get("/api/v1/customer/orders/%s" % self.oid)
        self.assertEqual(response.status_code, 200)
        fulfillment = response.json()["order"]["fulfillment"]
        self.assertEqual(tuple(sorted(fulfillment.keys())), tuple(sorted(FULFILLMENT_KEYS)))
        self.assertEqual(fulfillment["method"], "shipping")
        self.assertEqual(fulfillment["status"], "packed")
        self.assertIsNotNone(fulfillment["packed_at"])


class ActionItemSignalTests(unittest.TestCase):
    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db

    def _hub(self):
        return OperationsHubService(SimpleNamespace(database=self.db, shop_settings={}))

    def _quote(self, number, status, age_hours, customer="Acme"):
        qid = str(uuid.uuid4())
        created = (datetime.now() - timedelta(hours=age_hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.connect() as c:
            c.execute(
                "INSERT INTO quotes(id,quote_number,status,created_at) VALUES(?,?,?,?)",
                (qid, number, status, created))
            c.commit()
        return qid

    def _order(self, number, status, age_hours):
        oid = str(uuid.uuid4())
        created = (datetime.now() - timedelta(hours=age_hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self.db.connect() as c:
            c.execute(
                "INSERT INTO orders(id,order_number,status,total_cents,created_at) VALUES(?,?,?,?,?)",
                (oid, number, status, 0, created))
            c.commit()
        return oid

    def _by_key(self, items, prefix):
        return [i for i in items if str(i.get("key", "")).startswith(prefix)]

    def test_unpriced_quote_severity_ages(self):
        old = self._quote("Q-OLD", "draft", 30)
        fresh = self._quote("Q-NEW", "draft", 2)
        review = self._quote("Q-REV", "under_review", 50)
        items = self._by_key(self._hub().action_items(), "unpriced:")
        by_id = {i["id"]: i for i in items}
        self.assertEqual(by_id[old]["severity"], "high")
        self.assertEqual(by_id[fresh]["severity"], "medium")
        self.assertEqual(by_id[review]["severity"], "high")
        for item in by_id.values():
            self.assertEqual(item["page"], "Quotes")
            self.assertTrue(item["id"])
            self.assertEqual(item["title"], "Quote needs pricing")

    def test_sent_quote_not_double_counted_as_unpriced(self):
        self._quote("Q-SENT", "sent", 30)
        items = self._by_key(self._hub().action_items(), "unpriced:")
        self.assertEqual(items, [])

    def test_awaiting_approval_escalates_after_7_days(self):
        stale = self._quote("Q-STALE", "sent", 8 * 24)
        fresh = self._quote("Q-FRESH", "sent", 2 * 24)
        items = {i["id"]: i for i in self._by_key(self._hub().action_items(), "quote:")}
        self.assertEqual(items[stale]["severity"], "high")
        self.assertEqual(items[stale]["title"], "Quote awaiting approval")
        self.assertEqual(items[fresh]["severity"], "medium")

    def test_unstarted_order_severity_ages(self):
        old = self._order("O-OLD", "pending", 50)
        fresh = self._order("O-NEW", "confirmed", 5)
        items = self._by_key(self._hub().action_items(), "unstarted:")
        by_id = {i["id"]: i for i in items}
        self.assertEqual(by_id[old]["severity"], "high")
        self.assertEqual(by_id[fresh]["severity"], "medium")
        self.assertEqual(by_id[old]["page"], "Orders")
        self.assertIn("production not started", by_id[old]["title"])

    def test_order_with_active_job_not_flagged(self):
        oid = self._order("O-BUSY", "pending", 72)
        with self.db.connect() as c:
            c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",
                      (str(uuid.uuid4()), oid, "queued"))
            c.commit()
        items = self._by_key(self._hub().action_items(), "unstarted:")
        self.assertEqual([i["id"] for i in items], [])

    def test_order_with_only_dead_jobs_is_flagged(self):
        oid = self._order("O-DEAD", "pending", 72)
        with self.db.connect() as c:
            c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",
                      (str(uuid.uuid4()), oid, "completed"))
            c.execute("INSERT INTO print_jobs(id,order_id,status) VALUES(?,?,?)",
                      (str(uuid.uuid4()), oid, "cancelled"))
            c.commit()
        items = self._by_key(self._hub().action_items(), "unstarted:")
        self.assertEqual([i["id"] for i in items], [oid])
        self.assertEqual(items[0]["severity"], "high")


class DashboardCapTests(unittest.TestCase):
    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db
        self.fake_items = [
            {"severity": "medium", "title": "t%d" % n, "detail": "d",
             "page": "Orders", "id": "x%d" % n, "key": "k%d" % n}
            for n in range(25)
        ]

    def _fastapi(self):
        core = SimpleNamespace(
            database=self.db,
            shop_settings={},
            operations=SimpleNamespace(action_items=lambda: list(self.fake_items)),
            permissions=_Permissions(),
            production_automation=SimpleNamespace(last_run=None),
        )
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "u1", "account_type": "administrator", "role": "owner"}
        return TestClient(app)

    def _wsgi(self):
        core = SimpleNamespace(
            database=self.db,
            shop_settings={},
            operations=SimpleNamespace(action_items=lambda: list(self.fake_items)),
            production_automation=SimpleNamespace(last_run=None),
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": "u1", "account_type": "administrator"}),
            accounts=SimpleNamespace(get_user=lambda uid: {"id": uid, "role": "owner"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        return FabOSAPI(core), {"Authorization": "Bearer <redacted>"}

    def test_fastapi_dashboard_cap_and_all(self):
        client = self._fastapi()
        body = client.get("/api/v1/admin/operations/dashboard").json()
        self.assertEqual(len(body["action_items"]), 20)
        body = client.get("/api/v1/admin/operations/dashboard?all=true").json()
        self.assertEqual(len(body["action_items"]), 25)
        body = client.get("/api/v1/admin/operations/dashboard?limit=5").json()
        self.assertEqual(len(body["action_items"]), 5)

    def test_wsgi_dashboard_cap_and_all(self):
        api, headers = self._wsgi()
        result = api.request("GET", "/api/v1/admin/operations/dashboard", {}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(len(result["data"]["action_items"]), 20)
        result = api.request("GET", "/api/v1/admin/operations/dashboard?all=true", {}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(len(result["data"]["action_items"]), 25)
        result = api.request("GET", "/api/v1/admin/operations/dashboard?limit=7", {}, headers)
        self.assertEqual(len(result["data"]["action_items"]), 7)


class StaffUnreadCountTests(unittest.TestCase):
    """GET /api/v1/admin/notifications/unread-count (staff-scoped).

    The customer unread-count endpoint 409s for team sessions, so the admin
    header badge needs its own route backed by the operations-hub
    notifications table.
    """

    def _fastapi(self, account_type="administrator"):
        core = SimpleNamespace(
            database=self.db,
            operations=SimpleNamespace(unread_count=lambda: 7),
            permissions=_Permissions(),
        )
        app = create_app(core)
        app.dependency_overrides[app.state.current_user] = lambda: {
            "id": "u1", "account_type": account_type, "role": "owner"}
        return TestClient(app)

    def _wsgi(self, account_type="administrator"):
        core = SimpleNamespace(
            database=self.db,
            operations=SimpleNamespace(unread_count=lambda: 7),
            shop_settings={},
            security=SimpleNamespace(
                context=lambda token, permission=None: {"id": "u1", "account_type": account_type}),
            accounts=SimpleNamespace(get_user=lambda uid: {"id": uid, "role": "owner"}),
            error_log=SimpleNamespace(error=lambda *a, **k: None),
        )
        return FabOSAPI(core), {"Authorization": "Bearer <redacted>"}

    def setUp(self):
        self.hold = _Db()
        self.addCleanup(self.hold.close)
        self.db = self.hold.db

    def test_fastapi_staff_unread_count(self):
        body = self._fastapi().get("/api/v1/admin/notifications/unread-count").json()
        self.assertEqual(body, {"unread": 7})

    def test_fastapi_non_admin_forbidden(self):
        response = self._fastapi("customer").get("/api/v1/admin/notifications/unread-count")
        self.assertEqual(response.status_code, 403)

    def test_wsgi_staff_unread_count(self):
        api, headers = self._wsgi()
        result = api.request("GET", "/api/v1/admin/notifications/unread-count", {}, headers)
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"], {"unread": 7})


if __name__ == "__main__":
    unittest.main()
