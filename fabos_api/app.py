import json
from urllib.parse import parse_qs, urlsplit


class FabOSAPI:
    """Small, dependency-free transport adapter over the existing FabOS core.

    The adapter owns HTTP-shaped request/response concerns only. Pricing,
    ownership, permissions, order transitions, invoices, and fulfillment stay
    in the existing business services.
    """

    VERSION = "v1"

    def __init__(self, core):
        self.core = core

    @staticmethod
    def _row(value):
        if value is None:
            return None
        try:
            return dict(value)
        except (TypeError, ValueError):
            return value

    @classmethod
    def _jsonable(cls, value):
        if isinstance(value, dict):
            return {str(k): cls._jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._jsonable(v) for v in value]
        return cls._row(value)

    @staticmethod
    def _auth_token(headers):
        headers = headers or {}
        value = headers.get("Authorization") or headers.get("authorization") or ""
        if value.lower().startswith("bearer "):
            return value[7:].strip()
        return ""

    def _context(self, headers, permission=None):
        token = self._auth_token(headers)
        if not token:
            raise PermissionError("Authentication required")
        return self.core.security.context(token, permission=permission)

    def _response(self, status, data):
        return {"status": int(status), "data": self._jsonable(data)}

    def _error(self, exc):
        if isinstance(exc, PermissionError):
            return self._response(403 if "required" not in str(exc).lower() else 401,
                                  {"error": str(exc) or "Access denied"})
        if isinstance(exc, KeyError):
            return self._response(404, {"error": str(exc).strip("'")})
        if isinstance(exc, (ValueError, TypeError)):
            return self._response(400, {"error": str(exc)})
        try:
            self.core.error_log.error("API request failed", exc)
        except Exception:
            pass
        return self._response(500, {"error": "Internal server error"})

    def request(self, method, path, body=None, headers=None):
        """Handle one API request and return a transport-neutral response dict."""
        method = (method or "GET").upper()
        parsed = urlsplit(path or "/")
        route = [p for p in parsed.path.strip("/").split("/") if p]
        query = parse_qs(parsed.query, keep_blank_values=True)
        body = body or {}
        try:
            if route == ["api", self.VERSION, "health"] and method == "GET":
                return self._response(200, {"ok": True, "service": "FabOS", "api_version": self.VERSION})

            if route == ["api", self.VERSION, "auth", "login"] and method == "POST":
                result = self.core.auth.login(body.get("identifier", ""), body.get("password", ""),
                                              ip_address=(headers or {}).get("X-Forwarded-For"),
                                              user_agent=(headers or {}).get("User-Agent"))
                return self._response(200, result)

            if route == ["api", self.VERSION, "auth", "logout"] and method == "POST":
                token = self._auth_token(headers)
                if not token:
                    raise PermissionError("Authentication required")
                return self._response(200, {"logged_out": bool(self.core.auth.logout(token))})

            if route == ["api", self.VERSION, "me"] and method == "GET":
                context = self._context(headers)
                return self._response(200, {"user": self.core.accounts.account_summary(context["id"])})

            if route[:3] == ["api", self.VERSION, "orders"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "order.read")
                    rows = self.core.orders.list_for_user(
                        context["id"],
                        query.get("q", [""])[0],
                        query.get("status", ["All"])[0],
                        query.get("sort", ["created"])[0],
                        query.get("desc", ["1"])[0] not in ("0", "false", "no"),
                        query.get("group", ["all"])[0],
                    )
                    return self._response(200, {"orders": rows})
                if len(route) == 4:
                    order_id = route[3]
                    if method == "GET":
                        context = self._context(headers, "order.read")
                        order, items = self.core.orders.get_for_user(context["id"], order_id)
                        return self._response(200, {"order": order, "items": items})
                    if method in ("PATCH", "PUT"):
                        context = self._context(headers, "order.manage")
                        status = body.get("status")
                        if not status:
                            raise ValueError("status is required")
                        order = self.core.orders.set_status(order_id, status, actor_user_id=context["id"])
                        return self._response(200, {"order": order})

            if route[:3] == ["api", self.VERSION, "invoices"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "payment.read")
                    rows = self.core.invoices.list_for_user(
                        context["id"], query.get("q", [""])[0], query.get("status", ["All"])[0],
                        query.get("sort", ["created"])[0],
                        query.get("desc", ["1"])[0] not in ("0", "false", "no"),
                    )
                    return self._response(200, {"invoices": rows})
                if len(route) == 4 and method == "GET":
                    context = self._context(headers, "payment.read")
                    invoice, items, payments = self.core.invoices.get_for_user(context["id"], route[3])
                    return self._response(200, {"invoice": invoice, "items": items, "payments": payments})

            if route[:3] == ["api", self.VERSION, "fulfillments"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "fulfillment.read")
                    rows = self.core.fulfillment.list_for_user(context["id"])
                    return self._response(200, {"fulfillments": rows})
                if len(route) == 4 and method == "GET":
                    context = self._context(headers, "fulfillment.read")
                    row = self.core.fulfillment.get_for_user(context["id"], route[3])
                    return self._response(200, {"fulfillment": row})

            return self._response(404, {"error": "API route not found"})
        except Exception as exc:
            return self._error(exc)


def create_wsgi_app(core):
    """Create a minimal WSGI adapter using only the Python standard library."""
    api = FabOSAPI(core)

    def application(environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        raw = environ["wsgi.input"].read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = {}
        headers = {"Authorization": environ.get("HTTP_AUTHORIZATION", ""),
                   "User-Agent": environ.get("HTTP_USER_AGENT", ""),
                   "X-Forwarded-For": environ.get("REMOTE_ADDR", "")}
        result = api.request(environ.get("REQUEST_METHOD", "GET"),
                             environ.get("PATH_INFO", "/") + (("?" + environ["QUERY_STRING"]) if environ.get("QUERY_STRING") else ""),
                             body, headers)
        payload = json.dumps(result["data"], default=str).encode("utf-8")
        status_text = {200: "OK", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
                       404: "Not Found", 500: "Internal Server Error"}.get(result["status"], "OK")
        start_response("%d %s" % (result["status"], status_text),
                       [("Content-Type", "application/json; charset=utf-8"),
                        ("Content-Length", str(len(payload)))])
        return [payload]

    return application
