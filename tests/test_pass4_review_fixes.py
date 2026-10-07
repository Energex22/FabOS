"""Regression tests for the fourth review pass fixes.

- B-M1: WSGI registration is rate-limited through the __init__.py
  monkey-patch (the app.py register route is unreachable dead code).
- B-M2: _parse_multipart keeps repeated file field names as lists; the
  analyze-reference route receives every uploaded image.
- B-M3: WSGI payment-session maps PaymentProviderNotConfigured -> 503,
  PaymentProviderError -> 502, ValueError -> 409.
- B-M4: WSGI printer preheat rejects out-of-range hotend/bed with 400.
- B-M5: WSGI multipart quote-request upload is rate-limited (30/hr/IP).
- B-L6: CAD prompt capped at 12000, revision instruction at 8000 (422).
- B-L7: admin settings PUT treats {"value": 0} as 0, not "".
- B-L8: public upload field length caps are enforced.
- F-M2: WSGI text-only customer quote creation attaches cad_job_id.
"""
import io
import unittest
from types import SimpleNamespace

import fabos_api  # noqa: F401  (applies the WSGI route monkey-patch)
from fabos_api.app import FabOSAPI, _parse_multipart, create_wsgi_app
from fabos_core.services.cad_generation import CadGenerationError
from fabos_core.services.payments import PaymentProviderError, PaymentProviderNotConfigured

CUSTOMER = {"Authorization": " ".join(['Bearer', "customer-test-token-9f3"])}
ADMIN = {"Authorization": " ".join(['Bearer', "admin-test-token-9f3"])}


class _Security:
    def __init__(self, mapping):
        self._mapping = mapping

    def context(self, token, permission=None):
        if token in self._mapping:
            return dict(self._mapping[token])
        raise PermissionError("Invalid or expired session")


def _customer_security():
    return _Security({"customer-test-token-9f3": {"id": "u1", "account_type": "customer"}})


def _admin_security():
    return _Security({"admin-test-token-9f3": {"id": "a1", "account_type": "administrator"}})


def _quiet_core(**overrides):
    base = {"error_log": SimpleNamespace(error=lambda *a, **k: None)}
    base.update(overrides)
    return SimpleNamespace(**base)


class _Conn:
    """Recording in-memory stand-in for a DB connection."""

    def __init__(self, fetchone_result=None):
        self.executed = []
        self.fetchone_result = fetchone_result

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        self.executed.append(a[0] if a else "")
        return self

    def fetchone(self):
        return self.fetchone_result

    def commit(self):
        pass


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


def _multipart_parts(parts, boundary="----pass4boundary"):
    """parts: list of (name, bytes_value, filename_or_None)."""
    chunks = []
    for name, value, fname in parts:
        header = 'Content-Disposition: form-data; name="%s"' % name
        if fname:
            header += '; filename="%s"\r\nContent-Type: application/octet-stream' % fname
        chunks.append(("--" + boundary + "\r\n" + header + "\r\n\r\n").encode() + value + b"\r\n")
    chunks.append(("--" + boundary + "--\r\n").encode())
    return b"".join(chunks), "multipart/form-data; boundary=%s" % boundary


class Bm1RegisterRateLimitTests(unittest.TestCase):
    """B-M1: the register rate limiter is enforced inside the __init__ patch."""

    class _StubRegisterService:
        def __init__(self, database, accounts, auth, shop_settings=None):
            pass

        def register(self, name, email, password, phone=""):
            return {"token": "tok", "expires_at": "never", "user": {}}

    def _core(self):
        return _quiet_core(database=SimpleNamespace(), accounts=SimpleNamespace(),
                           auth=SimpleNamespace())

    def test_register_rate_limit_enforced_through_patch(self):
        real = fabos_api.CustomerAccountService
        fabos_api.CustomerAccountService = self._StubRegisterService
        try:
            api = FabOSAPI(self._core())
            headers = {"X-Direct-Peer": "203.0.113.9"}
            statuses = []
            for i in range(11):
                result = api.request(
                    "POST", "/api/v1/auth/register",
                    {"name": "N", "email": "u%d@example.com" % i, "password": "secret-password"},
                    headers,
                )
                statuses.append(result["status"])
            self.assertEqual(statuses[:10], [201] * 10)
            self.assertEqual(statuses[10], 429)
            self.assertIn("retry_after", result["data"])
            self.assertIn("registration", result["data"]["error"].lower())
        finally:
            fabos_api.CustomerAccountService = real

    def test_register_limit_is_per_ip(self):
        real = fabos_api.CustomerAccountService
        fabos_api.CustomerAccountService = self._StubRegisterService
        try:
            api = FabOSAPI(self._core())
            for i in range(10):
                result = api.request(
                    "POST", "/api/v1/auth/register",
                    {"name": "N", "email": "a%d@example.com" % i, "password": "secret-password"},
                    {"X-Direct-Peer": "203.0.113.10"},
                )
                self.assertEqual(result["status"], 201)
            # A different IP still has a full quota.
            result = api.request(
                "POST", "/api/v1/auth/register",
                {"name": "N", "email": "other@example.com", "password": "secret-password"},
                {"X-Direct-Peer": "203.0.113.11"},
            )
            self.assertEqual(result["status"], 201)
        finally:
            fabos_api.CustomerAccountService = real


class Bm2MultipartListTests(unittest.TestCase):
    """B-M2: repeated file field names are all kept, not overwritten."""

    def _three_files_body(self):
        return _multipart_parts([
            ("files", b"\x89PNG\r\n\x1a\nimg0", "img0.png"),
            ("files", b"\x89PNG\r\n\x1a\nimg1", "img1.png"),
            ("files", b"\x89PNG\r\n\x1a\nimg2", "img2.png"),
        ])

    def test_repeated_file_fields_all_kept(self):
        body, ctype = self._three_files_body()
        fields, files = _parse_multipart(body, ctype)
        self.assertIn("files", files)
        self.assertEqual(len(files["files"]), 3)
        self.assertEqual([name for name, _ in files["files"]],
                         ["img0.png", "img1.png", "img2.png"])
        self.assertEqual([payload for _, payload in files["files"]],
                         [b"\x89PNG\r\n\x1a\nimg0", b"\x89PNG\r\n\x1a\nimg1", b"\x89PNG\r\n\x1a\nimg2"])

    def test_single_file_field_is_one_entry_list(self):
        body, ctype = _multipart_parts([("file", b"model-bytes", "model.stl")])
        fields, files = _parse_multipart(body, ctype)
        self.assertEqual(files["file"], [("model.stl", b"model-bytes")])

    def test_analyze_reference_receives_all_images(self):
        seen = {}

        class _AI:
            def design_spec_from_images(self, images, reference_note=""):
                seen["count"] = len(images)
                return {"metadata": {}}

        core = _quiet_core(security=_customer_security(), ai=_AI())
        app = create_wsgi_app(core)
        body, ctype = self._three_files_body()
        status, _ = _wsgi_call(app, "POST", "/api/v1/customer/cad/analyze-reference",
                              body=body, content_type=ctype, headers=CUSTOMER)
        self.assertTrue(status.startswith("200"), status)
        self.assertEqual(seen.get("count"), 3)


class Bm3PaymentSessionMappingTests(unittest.TestCase):
    """B-M3: provider failures map to 503/502/409, not 500/400."""

    def _api(self, exc=None, row=None):
        class _Payments:
            def create_checkout(self, user_id, order_id):
                if exc is not None:
                    raise exc
                return row

        core = _quiet_core(security=_customer_security(), payments=_Payments())
        return FabOSAPI(core)

    def _call(self, api):
        return api.request("POST", "/api/v1/customer/orders/o1/payment-session",
                           {}, CUSTOMER)

    def test_not_configured_maps_to_503(self):
        result = self._call(self._api(exc=PaymentProviderNotConfigured("no provider")))
        self.assertEqual(result["status"], 503)

    def test_provider_error_maps_to_502(self):
        result = self._call(self._api(exc=PaymentProviderError("boom")))
        self.assertEqual(result["status"], 502)
        self.assertEqual(result["data"]["error"], "Payment provider request failed")

    def test_value_error_maps_to_409(self):
        result = self._call(self._api(exc=ValueError("Payment is not available for this order")))
        self.assertEqual(result["status"], 409)

    def test_success_projection_unchanged(self):
        result = self._call(self._api(row={"status": "open", "checkout_url": "https://pay/x",
                                          "internal_secret": "nope"}))
        self.assertEqual(result["status"], 200)
        self.assertEqual(result["data"]["payment"],
                         {"status": "open", "checkout_url": "https://pay/x"})
        self.assertNotIn("internal_secret", str(result["data"]))


class Bm4PreheatBoundsTests(unittest.TestCase):
    """B-M4: out-of-range hotend/bed targets are rejected with 400."""

    def _api(self):
        self.calls = {}

        def preheat_together(printer, hotend, bed):
            self.calls.update(hotend=hotend, bed=bed)
            return {"ok": True}

        conn = _Conn(fetchone_result={"id": "p1"})
        core = _quiet_core(
            security=_admin_security(),
            database=SimpleNamespace(connect=lambda: conn),
            octoprint_print=SimpleNamespace(preheat_together=preheat_together),
        )
        return FabOSAPI(core)

    def _call(self, api, payload):
        return api.request("POST", "/api/v1/admin/printers/p1/preheat", payload, ADMIN)

    def test_hotend_above_300_rejected(self):
        result = self._call(self._api(), {"hotend": 301})
        self.assertEqual(result["status"], 400)
        self.assertEqual(self.calls, {})

    def test_hotend_negative_rejected(self):
        result = self._call(self._api(), {"hotend": -1})
        self.assertEqual(result["status"], 400)

    def test_bed_above_130_rejected(self):
        result = self._call(self._api(), {"bed": 131})
        self.assertEqual(result["status"], 400)

    def test_bed_negative_rejected(self):
        result = self._call(self._api(), {"bed": -0.5})
        self.assertEqual(result["status"], 400)

    def test_non_numeric_rejected(self):
        result = self._call(self._api(), {"hotend": "lots"})
        self.assertEqual(result["status"], 400)

    def test_boundary_values_pass_through(self):
        api = self._api()
        result = self._call(api, {"hotend": 300, "bed": 130})
        self.assertEqual(result["status"], 200)
        self.assertEqual(self.calls, {"hotend": 300, "bed": 130})

    def test_zero_is_valid(self):
        api = self._api()
        result = self._call(api, {"hotend": 0, "bed": 0})
        self.assertEqual(result["status"], 200)

    def test_missing_temps_still_400(self):
        result = self._call(self._api(), {})
        self.assertEqual(result["status"], 400)


class Bm5UploadRateLimitTests(unittest.TestCase):
    """B-M5: the public multipart upload is rate-limited at 30/hr/IP."""

    def test_upload_rate_limit_enforced(self):
        core = _quiet_core(security=_customer_security())
        api = FabOSAPI(core)
        headers = dict(CUSTOMER)
        headers["X-Direct-Peer"] = "198.51.100.7"
        headers["Content-Type"] = "multipart/form-data; boundary=----x"
        statuses = []
        last = None
        for _ in range(31):
            last = api.request("POST", "/api/v1/quote-requests/upload", {}, headers, raw_body=b"")
            statuses.append(last["status"])
        # The first requests pass the limiter (and then fail on the empty
        # multipart body); the 31st is rejected by the limiter itself.
        self.assertEqual(statuses[0], 400)
        self.assertEqual(statuses[29], 400)
        self.assertEqual(statuses[30], 429)
        self.assertIn("retry_after", last["data"])


class Bl6CadCapsTests(unittest.TestCase):
    """B-L6: CAD prompt / revision instruction length caps."""

    def _api(self):
        cad = SimpleNamespace(
            generate=lambda **kw: {"job_id": "j", "spec": {}, "verification": {}, "artifacts": []},
            revise=lambda **kw: {"job_id": "j", "spec": {}, "verification": {}, "artifacts": []},
        )
        return FabOSAPI(_quiet_core(security=_customer_security(), cad_generation=cad))

    def test_generate_prompt_over_cap_rejected(self):
        result = self._api().request("POST", "/api/v1/customer/cad/generate",
                                     {"prompt": "x" * 12001}, CUSTOMER)
        self.assertEqual(result["status"], 422)

    def test_generate_prompt_at_cap_allowed(self):
        result = self._api().request("POST", "/api/v1/customer/cad/generate",
                                     {"prompt": "x" * 12000}, CUSTOMER)
        self.assertEqual(result["status"], 200)

    def test_revise_instruction_over_cap_rejected(self):
        result = self._api().request("POST", "/api/v1/customer/cad/jobs/" + "a" * 32 + "/revise",
                                     {"instruction": "x" * 8001}, CUSTOMER)
        self.assertEqual(result["status"], 422)

    def test_revise_instruction_at_cap_allowed(self):
        result = self._api().request("POST", "/api/v1/customer/cad/jobs/" + "a" * 32 + "/revise",
                                     {"instruction": "x" * 8000}, CUSTOMER)
        self.assertEqual(result["status"], 200)


class Bl7SettingsValueTests(unittest.TestCase):
    """B-L7: {"value": 0} is treated as 0, not ""."""

    def _api(self):
        seen = {}

        class _Settings:
            def set_validated(self, key, value):
                seen.update(key=key, value=value)

            def get(self, key, default=None):
                return seen.get("value")

            def metadata(self):
                return {}

        core = _quiet_core(security=_admin_security(),
                           accounts=SimpleNamespace(get_user=lambda uid: {"role": "owner"}),
                           shop_settings=_Settings())
        return FabOSAPI(core), seen

    def test_zero_value_kept(self):
        api, seen = self._api()
        result = api.request("PUT", "/api/v1/admin/settings",
                             {"key": "some_numeric_key", "value": 0}, ADMIN)
        self.assertEqual(result["status"], 200)
        self.assertEqual(seen["value"], "0")

    def test_false_value_kept(self):
        api, seen = self._api()
        result = api.request("PUT", "/api/v1/admin/settings",
                             {"key": "some_key", "value": False}, ADMIN)
        self.assertEqual(result["status"], 200)
        self.assertEqual(seen["value"], "False")

    def test_missing_value_still_empty_string(self):
        api, seen = self._api()
        result = api.request("PUT", "/api/v1/admin/settings", {"key": "some_key"}, ADMIN)
        self.assertEqual(result["status"], 200)
        self.assertEqual(seen["value"], "")


class Bl8UploadCapsTests(unittest.TestCase):
    """B-L8: public upload field length caps mirror FastAPI's pydantic caps."""

    def setUp(self):
        # The route lazily imports fabos_core.services.customer_api_writes,
        # which requires fastapi (not installed in minimal test envs). The
        # caps under test run before any of the imported helpers are used,
        # so a stub module keeps these tests hermetic.
        import sys
        import types
        mod = types.ModuleType("fabos_core.services.customer_api_writes")
        mod.ALLOWED_CUSTOM_UPLOAD_EXTENSIONS = {".stl"}
        mod.MAX_CUSTOM_UPLOAD_BYTES = 25 * 1024 * 1024
        mod._validate_model_file = lambda path, ext: None
        mod._create_public_quote = lambda core, customer_id, project: "q-stub"
        mod._public_quote = lambda quote: {"id": "q-stub", "quote_number": "Q-9"}
        real = sys.modules.get("fabos_core.services.customer_api_writes")
        sys.modules["fabos_core.services.customer_api_writes"] = mod

        def _restore():
            if real is None:
                sys.modules.pop("fabos_core.services.customer_api_writes", None)
            else:
                sys.modules["fabos_core.services.customer_api_writes"] = real

        self.addCleanup(_restore)

    def _api(self, **core_overrides):
        core = _quiet_core(security=_customer_security(), **core_overrides)
        return FabOSAPI(core)

    def _upload(self, api, fields, ip="192.0.2.9"):
        parts = [("file", b"solid-bytes", "model.stl")]
        parts.extend((name, value.encode("utf-8"), None) for name, value in fields.items())
        body, ctype = _multipart_parts(parts)
        headers = dict(CUSTOMER)
        headers["X-Direct-Peer"] = ip
        headers["Content-Type"] = ctype
        return api.request("POST", "/api/v1/quote-requests/upload", {}, headers, raw_body=body)

    def test_idea_over_4000_rejected(self):
        api = self._api()
        result = self._upload(api, {"name": "N", "email": "a@b.c", "idea": "x" * 4001})
        self.assertEqual(result["status"], 400)
        self.assertIn("idea", result["data"]["error"])

    def test_name_over_200_rejected(self):
        api = self._api()
        result = self._upload(api, {"name": "x" * 201, "email": "a@b.c", "idea": "box"})
        self.assertEqual(result["status"], 400)

    def test_email_over_320_rejected(self):
        api = self._api()
        result = self._upload(api, {"name": "N", "email": "x" * 316 + "@b.co", "idea": "box"})
        self.assertEqual(result["status"], 400)

    def test_notes_over_4000_rejected(self):
        api = self._api()
        result = self._upload(api, {"name": "N", "email": "a@b.c", "idea": "box",
                                    "notes": "x" * 4001})
        self.assertEqual(result["status"], 400)

    def test_caps_not_triggered_at_boundary(self):
        # Boundary-length fields pass validation and the request completes
        # (201), proving the caps only fire above the limits.
        core_overrides = {
            "customers": SimpleNamespace(
                list=lambda query: [{"id": "c1", "email": "a@b.c"}]),
            "quotes": SimpleNamespace(
                get=lambda qid: [{"id": qid, "quote_number": "Q-9"}]),
            "database": SimpleNamespace(connect=lambda: _Conn()),
            "design_vault": SimpleNamespace(import_file=lambda *a, **k: None),
        }
        api = self._api(**core_overrides)
        result = self._upload(api, {"name": "x" * 200, "email": "a@b.c",
                                    "idea": "x" * 4000, "dimensions": "x" * 1000,
                                    "material": "x" * 200, "notes": "x" * 4000})
        self.assertEqual(result["status"], 201, result["data"])
        self.assertEqual(result["data"]["request_number"], "Q-9")


class Fm2CadJobAttachTests(unittest.TestCase):
    """F-M2: text-only quote creation attaches payload.project.cad_job_id."""

    def _api(self, attach):
        conn = _Conn()

        def create_quote_request(user_id, project):
            return ({"id": "q1", "quote_number": "Q-1"}, [{"id": "i1"}])

        core = _quiet_core(
            security=_customer_security(),
            customer_commerce=SimpleNamespace(create_quote_request=create_quote_request),
            cad_generation=SimpleNamespace(attach_to_quote=attach),
            database=SimpleNamespace(connect=lambda: conn),
        )
        return FabOSAPI(core), conn

    def test_cad_job_id_attached(self):
        attached = {}

        def attach(job_id, quote_id, user_id):
            attached.update(job_id=job_id, quote_id=quote_id, user_id=user_id)
            return {"design_id": "d1"}

        api, _ = self._api(attach)
        result = api.request("POST", "/api/v1/customer/quotes",
                             {"project": {"idea": "a box", "cad_job_id": "job-1"}},
                             CUSTOMER)
        self.assertEqual(result["status"], 201)
        self.assertEqual(attached, {"job_id": "job-1", "quote_id": "q1", "user_id": "u1"})
        self.assertEqual(result["data"]["cad"], {"design_id": "d1"})

    def test_no_cad_job_id_no_attach(self):
        def attach(*args):
            raise AssertionError("attach_to_quote must not be called")

        api, _ = self._api(attach)
        result = api.request("POST", "/api/v1/customer/quotes",
                             {"idea": "a box"}, CUSTOMER)
        self.assertEqual(result["status"], 201)
        self.assertNotIn("cad", result["data"])

    def test_attach_failure_deletes_quote_and_returns_400(self):
        def attach(*args):
            raise CadGenerationError("Only completed CAD jobs can be attached to a quote")

        api, conn = self._api(attach)
        result = api.request("POST", "/api/v1/customer/quotes",
                             {"project": {"idea": "a box", "cad_job_id": "job-1"}},
                             CUSTOMER)
        self.assertEqual(result["status"], 400)
        self.assertTrue(any("DELETE FROM quotes" in stmt for stmt in conn.executed),
                        conn.executed)


if __name__ == "__main__":
    unittest.main()
