import base64
import binascii
import json
import threading
import time
from urllib.parse import parse_qs, urlsplit


class FabOSAPI:
    """Small, dependency-free transport adapter over the existing FabOS core."""

    VERSION = "v1"

    def __init__(self, core):
        self.core = core
        self._auth_attempts = {}
        self._auth_attempts_lock = threading.Lock()

    def _allow_auth_attempt(self, client_ip):
        now = time.monotonic()
        key = str(client_ip or "unknown").split(",")[0].strip()
        with self._auth_attempts_lock:
            attempts = [stamp for stamp in self._auth_attempts.get(key, []) if now - stamp < 900]
            if len(attempts) >= 10:
                self._auth_attempts[key] = attempts
                return False
            attempts.append(now)
            self._auth_attempts[key] = attempts
            return True

    def _clear_auth_attempts(self, client_ip):
        key = str(client_ip or "unknown").split(",")[0].strip()
        with self._auth_attempts_lock:
            self._auth_attempts.pop(key, None)

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
            return self._response(403 if "required" not in str(exc).lower() else 401, {"error": str(exc) or "Access denied"})
        if isinstance(exc, KeyError):
            return self._response(404, {"error": str(exc).strip("'")})
        if isinstance(exc, (ValueError, TypeError)):
            return self._response(400, {"error": str(exc)})
        try:
            self.core.error_log.error("API request failed", exc)
        except Exception:
            pass
        return self._response(500, {"error": "Internal server error"})

    @staticmethod
    def _public_product(row):
        if row is None:
            return None
        data = dict(row)
        return {
            "id": data.get("id"),
            "sku": data.get("sku"),
            "name": data.get("name"),
            "category": data.get("category") or "Other",
            "description": data.get("description") or "",
            "designer": data.get("designer") or "",
            "source_url": data.get("source_url") or "",
            "license_name": data.get("license_name") or "",
            "license_status": data.get("license_status") or "",
            "price": round(float(data.get("price_cents") or 0) / 100.0, 2),
            "estimated_minutes": data.get("estimated_minutes") or 0,
            "estimated_filament_g": data.get("estimated_filament_g") or 0,
        }

    @staticmethod
    def _public_images(rows):
        public = []
        for row in rows:
            item = dict(row)
            raw = str(item.get("path") or "").strip()
            source = str(item.get("source_url") or "").strip()
            if raw.startswith(("http://", "https://", "/")):
                item["url"] = raw
            else:
                continue
            public.append(item)
        return public

    def _operations_dashboard(self, user):\n        from datetime import datetime, timedelta\n        now=datetime.now(); today=now.date().isoformat(); month_start=(now.date()-timedelta(days=29)).isoformat()\n        with self.core.database.connect() as conn:\n            def scalar(sql,args=()): return conn.execute(sql,args).fetchone()[0] or 0\n            orders_today=int(scalar("SELECT COUNT(*) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')",(today,)))\n            sales_today=int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')",(today,)))\n            sales_30d=int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)>=date(?) AND status NOT IN ('cancelled')",(month_start,)))\n            active_orders=int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped')"))\n            active_jobs=int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('queued','scheduled','printing','paused')"))\n            printing_jobs=int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('printing','paused')"))\n            failed_jobs=int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status='failed'"))\n            printer_total=int(scalar("SELECT COUNT(*) FROM printers")); printer_online=int(scalar("SELECT COUNT(*) FROM printers WHERE lower(COALESCE(status,'')) NOT IN ('offline','error')"))\n            low_threshold=float(self.core.shop_settings.get("filament_low_threshold_g","250") or 250)\n            low_filament=int(scalar("SELECT COUNT(*) FROM filament_spools WHERE active=1 AND remaining_g<?",(low_threshold,)))\n            low_supplies=int(scalar("SELECT COUNT(*) FROM supply_items WHERE active=1 AND quantity<=low_threshold"))\n            open_quotes=int(scalar("SELECT COUNT(*) FROM quotes WHERE status IN ('draft','sent')")); unpaid=int(scalar("SELECT COUNT(*) FROM invoices WHERE status IN ('open','partial')"))\n            overdue=int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped') AND due_at IS NOT NULL AND due_at<?",(today,)))\n            pending_qc=int(scalar("SELECT COUNT(*) FROM qc_inspections WHERE status='pending'"))\n            recent_orders=[dict(x) for x in conn.execute("SELECT o.id,o.order_number,o.status,o.total_cents,o.due_at,o.created_at,COALESCE(c.name,'No customer') customer_name FROM orders o LEFT JOIN customers c ON c.id=o.customer_id ORDER BY o.created_at DESC LIMIT 8").fetchall()]\n            jobs=[dict(x) for x in conn.execute("SELECT j.id,j.status,j.estimated_minutes,j.print_time_left_seconds,COALESCE(p.name,'Custom Job') product_name,COALESCE(pr.name,'Unassigned') printer_name,COALESCE(o.order_number,'Personal') order_number,COALESCE(fs.material || ' ' || COALESCE(fs.color,''),'No spool') spool_name FROM print_jobs j LEFT JOIN products p ON p.id=j.product_id LEFT JOIN printers pr ON pr.id=j.printer_id LEFT JOIN orders o ON o.id=j.order_id LEFT JOIN filament_spools fs ON fs.id=j.spool_id WHERE j.status IN ('queued','scheduled','printing','paused','failed') ORDER BY CASE j.status WHEN 'failed' THEN 0 WHEN 'printing' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END,j.created_at LIMIT 12").fetchall()]\n            printers=[dict(x) for x in conn.execute("SELECT id,name,model,status,connection_mode,simulation_progress,nozzle_temp,bed_temp,print_time_seconds,print_time_left_seconds,octoprint_state_text,octoprint_current_file,last_seen_at,total_hours FROM printers ORDER BY name").fetchall()]\n            spools=[dict(x) for x in conn.execute("SELECT id,material,brand,color,remaining_g,initial_g,cost_cents,location FROM filament_spools WHERE active=1 AND remaining_g<? ORDER BY remaining_g LIMIT 10",(low_threshold,)).fetchall()]\n            maintenance=[dict(x) for x in conn.execute("SELECT p.id,p.name,p.total_hours,COALESCE(MAX(m.printer_hours),0) last_service_hours,p.total_hours-COALESCE(MAX(m.printer_hours),0) hours_since_service FROM printers p LEFT JOIN maintenance_records m ON m.printer_id=p.id GROUP BY p.id ORDER BY hours_since_service DESC").fetchall()]\n        try: actions=[dict(x) for x in self.core.operations_hub.action_items()[:20]]\n        except Exception: actions=[]\n        return {"generated_at":now.isoformat(timespec="seconds"),"viewer":{"id":user["id"],"account_type":user.get("account_type"),"role":user.get("role")},"business":{"orders_today":orders_today,"sales_today_cents":sales_today,"sales_30d_cents":sales_30d,"active_orders":active_orders,"open_quotes":open_quotes,"unpaid_invoices":unpaid,"overdue_orders":overdue,"pending_qc":pending_qc},"production":{"active_jobs":active_jobs,"printing_jobs":printing_jobs,"failed_jobs":failed_jobs,"jobs":jobs},"printers":{"total":printer_total,"online":printer_online,"items":printers},"inventory":{"low_filament":low_filament,"low_supplies":low_supplies,"filament_threshold_g":low_threshold,"spools":spools},"maintenance":{"items":maintenance},"recent_orders":recent_orders,"action_items":actions}\n\n    def request(self, method, path, body=None, headers=None):
        method = (method or "GET").upper()
        parsed = urlsplit(path or "/")
        route = [p for p in parsed.path.strip("/").split("/") if p]
        query = parse_qs(parsed.query, keep_blank_values=True)
        body = body or {}
        try:
            if route == ["api", self.VERSION, "health"] and method == "GET":
                return self._response(200, {"ok": True, "service": "FabOS", "api_version": self.VERSION})

            if route == ["api", self.VERSION, "admin", "operations", "dashboard"] and method == "GET":\n                context=self._context(headers, "production.read")\n                return self._response(200, self._operations_dashboard(context))\n\n            if route == ["api", self.VERSION, "catalog"] and method == "GET":
                rows = self.core.products.customer_catalog(
                    query.get("q", [""])[0], query.get("category", ["All"])[0],
                    query.get("sort", ["name"])[0],
                    query.get("desc", ["0"])[0] not in ("0", "false", "no"),
                )
                return self._response(200, {"products": [{**self._public_product(row), "images": self._public_images(self.core.products.images(row["id"]))} for row, _readiness in rows]})

            if route == ["api", self.VERSION, "catalog", "categories"] and method == "GET":
                rows = self.core.products.customer_catalog()
                categories = sorted({str(row["category"] or "Other") for row, _readiness in rows if str(row["category"] or "").strip()})
                return self._response(200, {"categories": categories})

            if len(route) == 4 and route[:3] == ["api", self.VERSION, "catalog"] and method == "GET":
                product = self.core.products.get(route[3])
                if product is None:
                    raise KeyError("Product not found")
                return self._response(200, {
                    "product": self._public_product(product),
                    "images": self._public_images(self.core.products.images(route[3])),
                    "variants": [dict(row) for row in self.core.products.variants(route[3])],
                })

            if route == ["api", self.VERSION, "auth", "login"] and method == "POST":
                client_ip = (headers or {}).get("X-Forwarded-For", "")
                if not self._allow_auth_attempt(client_ip):
                    return self._response(429, {"error": "Too many sign-in attempts. Please try again later."})
                result = self.core.auth.login(body.get("identifier", ""), body.get("password", ""),
                                              ip_address=client_ip,
                                              user_agent=(headers or {}).get("User-Agent"))
                if result:
                    account = result.get("user", {}).get("user", {}) if isinstance(result.get("user"), dict) else {}
                    if str(account.get("account_type") or "").lower() != "customer":
                        self.core.auth.logout(result.get("token", ""))
                        return self._response(401, {"error": "This sign-in is not available through the customer storefront."})
                    self._clear_auth_attempts(client_ip)
                    return self._response(200, result)
                return self._response(401, {"error": "Invalid email/username or password"})

            if route == ["api", self.VERSION, "auth", "logout"] and method == "POST":
                token = self._auth_token(headers)
                if not token:
                    raise PermissionError("Authentication required")
                return self._response(200, {"logged_out": bool(self.core.auth.logout(token))})

            if route == ["api", self.VERSION, "me"] and method == "GET":
                context = self._context(headers)
                return self._response(200, {"user": self.core.accounts.account_summary(context["id"])})

            if route == ["api", self.VERSION, "customer", "me"] and method == "GET":
                context = self._context(headers)
                return self._response(200, self.core.accounts.account_summary(context["id"]))

            if route == ["api", self.VERSION, "customer", "me"] and method == "PATCH":
                context = self._context(headers)
                customer = self.core.accounts.customer_for_user(context["id"])
                if not customer:
                    raise PermissionError("Customer account is not linked")
                allowed = {"name", "email", "phone", "notes"}
                payload = {key: body.get(key) for key in allowed if key in body}
                if payload:
                    self.core.customers.save(payload, customer["id"])
                return self._response(200, self.core.accounts.account_summary(context["id"]))

            if route == ["api", self.VERSION, "customer", "quotes"] and method == "POST":
                context = self._context(headers)
                quote, items = self.core.customer_commerce.create_quote_request(context["id"], body.get("project") or body)
                return self._response(201, {"quote": quote, "items": items, "quote_number": quote["quote_number"]})

            if route == ["api", self.VERSION, "customer", "quotes"] and method == "GET":
                context = self._context(headers)
                return self._response(200, {"quotes": self.core.quotes.list_for_user(context["id"])})

            if len(route) == 5 and route[:4] == ["api", self.VERSION, "customer", "quotes"] and method == "GET":
                context = self._context(headers)
                quote, items = self.core.quotes.get_for_user(context["id"], route[4])
                return self._response(200, {"quote": quote, "items": items})

            if route == ["api", self.VERSION, "customer", "orders"] and method == "POST":
                context = self._context(headers)
                payload = body or {}
                result = self.core.customer_commerce.create_order(
                    context["id"], payload.get("items") or [],
                    payload.get("shippingAddress") or payload.get("shipping_address") or {},
                    payload.get("notes") or ""
                )
                order, saved_items, subtotal, shipping, tax, total = result
                return self._response(201, {
                    "order": dict(order),
                    "items": [dict(item) for item in saved_items],
                    "totals": {
                        "subtotal": subtotal / 100.0,
                        "shipping": shipping / 100.0,
                        "tax": tax / 100.0,
                        "total": total / 100.0,
                    },
                })

            if route == ["api", self.VERSION, "customer", "orders"] and method == "GET":
                context = self._context(headers)
                return self._response(200, {"orders": self.core.orders.list_for_user(context["id"])})

            if len(route) == 5 and route[:4] == ["api", self.VERSION, "customer", "orders"] and method == "GET":
                context = self._context(headers)
                order, items = self.core.orders.get_for_user(context["id"], route[4])
                return self._response(200, {"order": order, "items": items})

            if len(route) == 6 and route[:5] == ["api", self.VERSION, "customer", "orders"] and route[5] == "payment-session" and method == "POST":
                context = self._context(headers)
                payment = self.core.payments.create_checkout(context["id"], route[4])
                return self._response(200, {"payment": payment})

            if route == ["api", self.VERSION, "auth", "register"] and method == "POST":
                result = self.core.customer_commerce.register_customer(
                    body.get("name", ""), body.get("email", ""), body.get("password", ""), body.get("phone", "")
                )
                return self._response(201, result)

            if route == ["api", self.VERSION, "quote-requests"] and method == "POST":
                file_bytes = None
                file_base64 = body.get("file_base64") or ""
                if file_base64:
                    try:
                        file_bytes = base64.b64decode(file_base64, validate=True)
                    except (ValueError, binascii.Error) as exc:
                        raise ValueError("Reference file payload is invalid") from exc
                    if len(file_bytes) > 25 * 1024 * 1024:
                        raise ValueError("Reference file exceeds the 25 MB limit")
                quote, items = self.core.customer_commerce.create_public_quote_request(
                    body.get("name", ""),
                    body.get("email", ""),
                    body.get("project") or body,
                    body.get("file_name", ""),
                    file_bytes,
                )
                return self._response(201, {"quote": quote, "items": items, "request_number": quote["quote_number"]})

            if route[:3] == ["api", self.VERSION, "products"]:
                if len(route) == 3 and method == "GET":
                    self._context(headers, "product.read")
                    rows = self.core.products.list(query.get("q", [""])[0], query.get("category", ["All"])[0],
                                                   query.get("license", ["All"])[0], query.get("sort", ["name"])[0],
                                                   query.get("desc", ["0"])[0] not in ("0", "false", "no"))
                    return self._response(200, {"products": rows})
                if len(route) == 4 and method == "GET":
                    self._context(headers, "product.read")
                    product = self.core.products.get(route[3])
                    if product is None:
                        raise KeyError("Product not found")
                    return self._response(200, {"product": product, "images": self.core.products.images(route[3]),
                                                "variants": self.core.products.variants(route[3])})

            if route[:3] == ["api", self.VERSION, "customers"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "customer.read")
                    account_type = context.get("account_type")
                    if account_type == "customer":
                        rows = self.core.customers.list_for_user(context["id"], query.get("q", [""])[0])
                    else:
                        rows = self.core.customers.list(query.get("q", [""])[0], query.get("sort", ["name"])[0],
                                                        query.get("desc", ["0"])[0] not in ("0", "false", "no"))
                    return self._response(200, {"customers": rows})
                if len(route) == 4 and method == "GET":
                    context = self._context(headers, "customer.read")
                    if context.get("account_type") == "customer":
                        customer = self.core.customers.get_for_user(context["id"], route[3])
                    else:
                        customer = self.core.customers.get(route[3])
                    return self._response(200, {"customer": customer})

            if route[:3] == ["api", self.VERSION, "quotes"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "quote.read")
                    if context.get("account_type") == "customer":
                        rows = self.core.quotes.list_for_user(context["id"], query.get("q", [""])[0],
                                                              query.get("status", ["All"])[0], query.get("sort", ["created"])[0],
                                                              query.get("desc", ["1"])[0] not in ("0", "false", "no"),
                                                              query.get("group", ["all"])[0])
                    else:
                        rows = self.core.quotes.list(query.get("q", [""])[0], query.get("status", ["All"])[0],
                                                     query.get("sort", ["created"])[0], query.get("desc", ["1"])[0] not in ("0", "false", "no"),
                                                     query.get("group", ["all"])[0])
                    return self._response(200, {"quotes": rows})
                if len(route) == 4 and method == "GET":
                    context = self._context(headers, "quote.read")
                    if context.get("account_type") == "customer":
                        quote, items = self.core.quotes.get_for_user(context["id"], route[3])
                    else:
                        quote, items = self.core.quotes.get(route[3])
                    return self._response(200, {"quote": quote, "items": items})

            if route[:3] == ["api", self.VERSION, "orders"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "order.read")
                    rows = self.core.orders.list_for_user(context["id"], query.get("q", [""])[0], query.get("status", ["All"])[0],
                                                          query.get("sort", ["created"])[0],
                                                          query.get("desc", ["1"])[0] not in ("0", "false", "no"), query.get("group", ["all"])[0])
                    return self._response(200, {"orders": rows})
                if len(route) == 4:
                    context = self._context(headers, "order.read" if method == "GET" else "order.manage")
                    if method == "GET":
                        order, items = self.core.orders.get_for_user(context["id"], route[3])
                        return self._response(200, {"order": order, "items": items})
                    if method in ("PATCH", "PUT"):
                        status = body.get("status")
                        if not status:
                            raise ValueError("status is required")
                        order = self.core.orders.set_status(route[3], status, actor_user_id=context["id"])
                        return self._response(200, {"order": order})

            if route[:3] == ["api", self.VERSION, "invoices"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "payment.read")
                    rows = self.core.invoices.list_for_user(context["id"], query.get("q", [""])[0], query.get("status", ["All"])[0],
                                                            query.get("sort", ["created"])[0],
                                                            query.get("desc", ["1"])[0] not in ("0", "false", "no"))
                    return self._response(200, {"invoices": rows})
                if len(route) == 4 and method == "GET":
                    context = self._context(headers, "payment.read")
                    invoice, items, payments = self.core.invoices.get_for_user(context["id"], route[3])
                    return self._response(200, {"invoice": invoice, "items": items, "payments": payments})

            if route[:3] == ["api", self.VERSION, "fulfillments"]:
                if len(route) == 3 and method == "GET":
                    context = self._context(headers, "fulfillment.read")
                    return self._response(200, {"fulfillments": self.core.fulfillment.list_for_user(context["id"])})
                if len(route) == 4 and method == "GET":
                    context = self._context(headers, "fulfillment.read")
                    return self._response(200, {"fulfillment": self.core.fulfillment.get_for_user(context["id"], route[3])})

            return self._response(404, {"error": "API route not found"})
        except Exception as exc:
            return self._error(exc)


def create_wsgi_app(core):
    api = FabOSAPI(core)

    def application(environ, start_response):
        length = int(environ.get("CONTENT_LENGTH") or 0)
        max_body = 36 * 1024 * 1024
        if length > max_body:
            payload = json.dumps({"error": "Request body is too large"}).encode("utf-8")
            start_response("413 Request Entity Too Large", [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), ("Content-Length", str(len(payload)))])
            return [payload]
        raw = environ["wsgi.input"].read(length) if length else b""
        try:
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except (ValueError, UnicodeDecodeError):
            body = {}
        headers = {"Authorization": environ.get("HTTP_AUTHORIZATION", ""), "User-Agent": environ.get("HTTP_USER_AGENT", ""),
                   "X-Forwarded-For": environ.get("HTTP_X_FORWARDED_FOR") or environ.get("REMOTE_ADDR", "")}
        result = api.request(environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "/") + (("?" + environ["QUERY_STRING"]) if environ.get("QUERY_STRING") else ""), body, headers)
        payload = json.dumps(result["data"], default=str).encode("utf-8")
        status_text = {200: "OK", 201: "Created", 400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found", 429: "Too Many Requests", 500: "Internal Server Error"}.get(result["status"], "OK")
        start_response("%d %s" % (result["status"], status_text), [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), ("Content-Length", str(len(payload)))])
        return [payload]

    return application
