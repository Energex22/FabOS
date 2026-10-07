"""Regression tests for the second-pass review fixes (HIGH + MEDIUMs).

- H1: WSGI checkout must ignore a client-supplied shipping_mode; the mode is
  server-authoritative (shop settings only).
- M1: WSGI serves POST /api/v1/customer/quotes/upload (multipart) via the same
  store_customer_quote_upload core as FastAPI.
- M2: WSGI maps authenticated-but-wrong-role PermissionErrors to 403, and only
  genuinely unauthenticated ones to 401.
- M3: WSGI serves POST /api/v1/webhooks/payments/{provider} with the raw body
  passed through untouched for signature verification.
- M4: design_proofs._public drops staff-authored notes; _admin keeps them.
"""
import io
import json
import struct
import unittest
from types import SimpleNamespace

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI, create_wsgi_app
from fabos_core.services.design_proofs import DesignProofService
from fabos_core.services.payments import PaymentProviderError, PaymentProviderNotConfigured


class _StubProducts:
    def is_customer_eligible(self, pid):
        return pid == "p1"

    def variants(self, pid):
        return []

    def get(self, pid):
        if pid == "p1":
            return {"id": "p1", "name": "Widget", "price_cents": 2000, "estimated_filament_g": 50}
        return None


class _StubSettings(dict):
    def get(self, key, default=None):
        return {"shipping_mode": "flat", "shipping_flat_cents": "500"}.get(key, default)


class _CustomerSecurity:
    def context(self, token, permission=None):
        if token == "tok":
            return {"id": "u1", "account_type": "customer"}
        if token == "emp":
            return {"id": "e1", "account_type": "employee"}
        raise PermissionError("Invalid or expired session")


def _quiet_core(**overrides):
    base = {"error_log": SimpleNamespace(error=lambda *a, **k: None)}
    base.update(overrides)
    return SimpleNamespace(**base)


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
    def part(name, value, fname=None):
        header = 'Content-Disposition: form-data; name="%s"' % name
        if fname:
            header += '; filename="%s"\r\nContent-Type: application/octet-stream' % fname
            return ("--" + boundary + "\r\n" + header + "\r\n\r\n").encode() + value + b"\r\n"
        return ("--" + boundary + "\r\n" + header + "\r\n\r\n" + value + "\r\n").encode()

    body = b"".join([part(k, v) for k, v in fields.items()])
    body += part(file_field, file_bytes, filename)
    body += ("--" + boundary + "--\r\n").encode()
    return body, "multipart/form-data; boundary=%s" % boundary


def _one_triangle_stl():
    return b"\x00" * 80 + struct.pack("<I", 1) + b"\x00" * 50


class H1ShippingModeTests(unittest.TestCase):
    """H1: the WSGI checkout must not let customers choose their shipping mode."""

    def _api(self, settings=None):
        core = _quiet_core(
            products=_StubProducts(),
            shop_settings=settings or _StubSettings(),
            security=_CustomerSecurity(),
        )
        return FabOSAPI(core)

    def test_body_shipping_mode_free_is_ignored(self):
        api = self._api()
        result = api.request(
            "POST", "/api/v1/checkout/estimate",
            {"items": [{"product_id": "p1", "quantity": 1}], "shipping_mode": "free"},
            {"Authorization": "Bearer tok"},
        )
        self.assertEqual(result["status"], 200)
        # Shop settings say flat/500c — the customer's "free" must not apply.
        self.assertEqual(result["data"]["shipping_cents"], 500)

    def test_invalid_shop_setting_falls_back_to_flat(self):
        class BadSettings(dict):
            def get(self, key, default=None):
                return {"shipping_mode": "bogus", "shipping_flat_cents": "500"}.get(key, default)

        api = self._api(BadSettings())
        result = api.request(
            "POST", "/api/v1/checkout/estimate",
            {"items": [{"product_id": "p1", "quantity": 1}]},
            {"Authorization": "Bearer tok"},
        )
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["shipping_cents"], 500)


class M2StatusMappingTests(unittest.TestCase):
    """M2: 401 only for unauthenticated callers; 403 for wrong-role callers."""

    def test_error_mapping(self):
        api = FabOSAPI(_quiet_core())
        for message in ("Authentication required", "Authentication token is required",
                        "Authenticated user is required",
                        "Authenticated user is inactive or not found",
                        "Invalid or expired session"):
            self.assertEqual(api._error(PermissionError(message))["status"], 401, message)
        for message in ("Customer account required", "Customer account is not linked",
                        "Fulfillment access denied", "Order access denied",
                        "Storefront is currently unavailable",
                        "Customer registration is currently disabled"):
            self.assertEqual(api._error(PermissionError(message))["status"], 403, message)

    def test_employee_on_customer_route_gets_403(self):
        core = _quiet_core(security=_CustomerSecurity(),
                           design_proofs=SimpleNamespace(list_for_customer=lambda uid: []))
        api = FabOSAPI(core)
        denied = api.request("GET", "/api/v1/customer/proofs",
                             headers={"Authorization": "Bearer emp"})
        self.assertEqual(denied["status"], 403)
        anonymous = api.request("GET", "/api/v1/customer/proofs")
        self.assertEqual(anonymous["status"], 401)


class _UploadCommerce:
    def create_quote_request(self, user_id, project):
        return ({"id": "q1", "quote_number": "Q-100"}, [{"id": "i1"}])


class _UploadConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        return self

    def fetchone(self):
        return None

    def commit(self):
        pass


class M1WsgiUploadTests(unittest.TestCase):
    """M1: WSGI serves the customer file-upload route via the shared core."""

    def _app(self, security=None):
        vault = SimpleNamespace(imported=[],
                                import_file=lambda design_id, path, make_primary=False:
                                    vault.imported.append(design_id),
                                remove_design=lambda design_id: None)
        core = _quiet_core(
            security=security or _CustomerSecurity(),
            customer_commerce=_UploadCommerce(),
            database=SimpleNamespace(connect=lambda: _UploadConn()),
            design_vault=vault,
            cad_generation=SimpleNamespace(attach_to_quote=lambda *a: None),
        )
        return create_wsgi_app(core), vault

    def test_multipart_upload_returns_201(self):
        app, vault = self._app()
        body, content_type = _multipart(
            {"idea": "a widget", "quantity": "2"}, "file", "model.stl", _one_triangle_stl())
        status, out = _wsgi_call(app, "POST", "/api/v1/customer/quotes/upload", body,
                                 {"Authorization": "Bearer tok"}, content_type)
        self.assertTrue(status.startswith("201"), out[:200])
        data = json.loads(out)
        self.assertEqual(data["request_number"], "Q-100")
        self.assertEqual(data["file"], {"name": "model.stl", "bytes": 134, "extension": ".stl"})
        self.assertEqual(vault.imported, [data["design_id"]])

    def test_invalid_model_returns_400_not_500(self):
        app, _ = self._app()
        body, content_type = _multipart({"idea": "a widget"}, "file", "evil.stl", b"\x00" * 50)
        status, out = _wsgi_call(app, "POST", "/api/v1/customer/quotes/upload", body,
                                 {"Authorization": "Bearer tok"}, content_type)
        self.assertTrue(status.startswith("400"), out[:200])

    def test_employee_gets_403(self):
        class EmployeeSecurity:
            def context(self, token, permission=None):
                return {"id": "e1", "account_type": "employee"}

        app, _ = self._app(security=EmployeeSecurity())
        body, content_type = _multipart({"idea": "a widget"}, "file", "model.stl", _one_triangle_stl())
        status, out = _wsgi_call(app, "POST", "/api/v1/customer/quotes/upload", body,
                                 {"Authorization": "Bearer emp"}, content_type)
        self.assertTrue(status.startswith("403"), out[:200])

    def test_non_multipart_body_is_rejected(self):
        app, _ = self._app()
        status, out = _wsgi_call(app, "POST", "/api/v1/customer/quotes/upload",
                                 b'{"idea": "x"}', {"Authorization": "Bearer tok"})
        self.assertTrue(status.startswith("400"), out[:200])


class _WebhookConn:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        class _R:
            def fetchone(self):
                return None

        return _R()

    def commit(self):
        pass


class M3WsgiWebhookTests(unittest.TestCase):
    """M3: WSGI receives provider webhooks with the raw body intact."""

    def _app(self, payments):
        core = _quiet_core(payments=payments,
                           database=SimpleNamespace(connect=lambda: _WebhookConn()))
        return create_wsgi_app(core)

    def test_raw_body_reaches_handler_untouched(self):
        seen = {}

        class Payments:
            def handle_webhook(self, payload, signature=None, provider_name=None):
                seen.update(payload=payload, signature=signature, provider=provider_name)
                return {"processed": True}

        app = self._app(Payments())
        raw = b'{"id":"evt_1","type":"payment_intent.succeeded"}'
        status, out = _wsgi_call(app, "POST", "/api/v1/webhooks/payments/stripe", raw,
                                 {"Stripe-Signature": "sig_1"})
        self.assertTrue(status.startswith("200"), out[:200])
        self.assertEqual(seen["payload"], raw)
        self.assertEqual(seen["signature"], "sig_1")
        self.assertEqual(seen["provider"], "stripe")
        self.assertTrue(json.loads(out)["processed"])

    def test_square_signature_header_is_used(self):
        seen = {}

        class Payments:
            def handle_webhook(self, payload, signature=None, provider_name=None):
                seen.update(signature=signature, provider=provider_name)
                return {"processed": True}

        app = self._app(Payments())
        status, _ = _wsgi_call(app, "POST", "/api/v1/webhooks/payments/square", b"{}",
                               {"X-Square-Hmacsha256-Signature": "sq_1"})
        self.assertTrue(status.startswith("200"))
        self.assertEqual(seen["signature"], "sq_1")
        self.assertEqual(seen["provider"], "square")

    def test_provider_error_maps_to_400(self):
        class Payments:
            def handle_webhook(self, payload, signature=None, provider_name=None):
                raise PaymentProviderError("bad signature")

        app = self._app(Payments())
        status, _ = _wsgi_call(app, "POST", "/api/v1/webhooks/payments/stripe", b"{}",
                               {"Stripe-Signature": "bad"})
        self.assertTrue(status.startswith("400"), status)

    def test_unconfigured_provider_maps_to_503(self):
        class Payments:
            def handle_webhook(self, payload, signature=None, provider_name=None):
                raise PaymentProviderNotConfigured("no key")

        app = self._app(Payments())
        status, _ = _wsgi_call(app, "POST", "/api/v1/webhooks/payments/stripe", b"{}",
                               {"Stripe-Signature": "x"})
        self.assertTrue(status.startswith("503"), status)


class M4ProofNotesTests(unittest.TestCase):
    """M4: staff notes stay out of the customer proof projection."""

    def _row(self):
        return {"id": "p1", "quote_id": "q1", "quote_number": "Q-1", "design_id": "d1",
                "design_version": 2, "asset_id": "a1", "status": "sent",
                "notes": "STAFF ONLY", "customer_comment": "looks good",
                "sent_at": "t", "approved_at": None, "created_at": "t",
                "updated_at": "t", "design_name": "Widget", "original_name": "p.png",
                "kind": "image", "width_mm": 1, "depth_mm": 2, "height_mm": 3}

    def test_public_projection_drops_staff_notes(self):
        svc = DesignProofService.__new__(DesignProofService)
        public = svc._public(self._row())
        self.assertNotIn("notes", public)
        self.assertEqual(public["customer_comment"], "looks good")

    def test_admin_projection_keeps_staff_notes(self):
        svc = DesignProofService.__new__(DesignProofService)
        admin = svc._admin(self._row())
        self.assertEqual(admin["notes"], "STAFF ONLY")


if __name__ == "__main__":
    unittest.main()
