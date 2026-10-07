import base64
import binascii
import json
import mimetypes
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from fabos_core.services.rate_limit import RateLimiter
from fabos_api.wsgi_extended import handle_extended_routes
from urllib.parse import parse_qs, urlsplit


def _mapping(value):
    """Best-effort conversion of sqlite rows / mappings to plain dicts."""
    if isinstance(value, dict):
        return value
    try:
        keys = value.keys()
    except AttributeError:
        keys = None
    if keys is not None:
        return {key: value[key] for key in keys}
    try:
        return dict(value)
    except (TypeError, ValueError):
        return None


_LOOPBACK_PEERS = frozenset({"127.0.0.1", "::1", "localhost"})


# Friendly customer-facing order statuses. Mirrors CUSTOMER_STATUS in
# fabos_core/api.py; kept as a local copy so the WSGI layer does not import
# the FastAPI application module (which would pull fastapi into WSGI-only
# deployments).
_CUSTOMER_STATUS = {
    "new": "Order received", "pending": "Order received", "confirmed": "Order received",
    "in_production": "Preparing your order", "production": "Preparing your order",
    "ready": "Final quality check", "shipped": "Shipping", "completed": "Delivered",
    "cancelled": "Cancelled",
}


def _rate_limit_client_ip(headers):
    """Resolve the client IP used to key rate limits.

    X-Forwarded-For is client-controlled, so it is only trusted when the
    direct TCP peer is loopback — i.e. a local reverse proxy such as Caddy
    (the supported production deployment) set the header. Otherwise the
    direct peer address is used, so rotating X-Forwarded-For cannot be used
    to bypass rate limits.
    """
    headers = headers or {}
    direct = str(headers.get("X-Direct-Peer") or "").strip()
    forwarded = str(headers.get("X-Forwarded-For") or "").strip()
    if forwarded and direct in _LOOPBACK_PEERS:
        return forwarded.split(",")[0].strip() or direct or "unknown"
    return direct or "unknown"


def _parse_multipart(body_bytes, content_type):
    """Parse a multipart/form-data body with the stdlib email parser.

    Returns ``(fields, files)`` where ``fields`` maps field name → text and
    ``files`` maps field name → ``(filename, bytes)``. Returns ``None`` when
    the content type is not multipart or the body cannot be parsed.
    """
    try:
        if not content_type or "multipart/form-data" not in str(content_type).lower():
            return None
        from email import policy
        from email.parser import BytesParser
        preamble = (
            "Content-Type: " + str(content_type) + "\r\n"
            "MIME-Version: 1.0\r\n"
            "\r\n"
        ).encode("latin-1") + (body_bytes or b"")
        msg = BytesParser(policy=policy.default).parsebytes(preamble)
        if not msg.is_multipart():
            return None
        fields = {}
        files = {}
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            payload = part.get_payload(decode=True) or b""
            filename = part.get_filename()
            if filename:
                files[name] = (filename, payload)
            else:
                fields[name] = payload.decode("utf-8", errors="replace")
        return fields, files
    except Exception:
        return None


class FabOSAPI:
    """Small, dependency-free transport adapter over the existing FabOS core."""

    VERSION = "v1"

    def __init__(self, core):
        self.core = core
        self._auth_attempts = {}
        self._auth_attempts_lock = threading.Lock()
        self._public_rate_limits = {
            "register": RateLimiter(10, 900),
            "quote": RateLimiter(5, 900),
            "team_login": RateLimiter(10, 900),
        }

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
            # Evict keys whose attempts all expired (or oldest first) so a long-lived
            # server cannot accumulate entries for clients that never return.
            if len(self._auth_attempts) > 10000:
                expired = [
                    key for key, stamps in self._auth_attempts.items()
                    if not any(stamp > now - 900 for stamp in stamps)
                ]
                for key in expired:
                    self._auth_attempts.pop(key, None)
                while len(self._auth_attempts) > 10000:
                    self._auth_attempts.pop(next(iter(self._auth_attempts)), None)
            return True

    def _allow_public_attempt(self, kind, client_ip):
        limiter = self._public_rate_limits[kind]
        key = "%s:%s" % (kind, str(client_ip or "unknown").split(",")[0].strip())
        return limiter.allow(key), limiter.retry_after(key)

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
        # Mirror FastAPI's _json (fabos_core/api.py): primitives pass through
        # untouched. Without this, _row() turns every empty string into {}
        # because dict('') succeeds and returns an empty dict.
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
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
        context = self.core.security.context(token, permission=permission)
        # Flatten actor fields onto the context itself so routes can rely on
        # context["id"] / context["account_type"] regardless of whether the
        # security layer returns a structured or legacy id-only context.
        if not isinstance(context, dict):
            return context
        normalized = dict(context)
        user = _mapping(context.get("user"))
        if user:
            normalized.setdefault("id", user.get("id"))
            normalized.setdefault("account_type", user.get("account_type"))
        if normalized.get("id") and not normalized.get("account_type"):
            try:
                summary = _mapping(self.core.accounts.account_summary(normalized["id"])) or {}
                summary_user = _mapping(summary.get("user"))
                if summary_user:
                    normalized.setdefault("account_type", summary_user.get("account_type"))
                normalized.setdefault("account_type", summary.get("account_type"))
            except Exception:
                pass
        return normalized

    def _response(self, status, data):
        return {"status": int(status), "data": self._jsonable(data)}

    # Messages that mean "no usable session" (→ 401). Every other
    # PermissionError means the caller IS authenticated but not allowed
    # (wrong role, unlinked account, disabled feature, denied action) → 403.
    _UNAUTHENTICATED_ERRORS = frozenset({
        "authentication required",
        "authentication token is required",
        "authenticated user is required",
        "authenticated user is inactive or not found",
        "invalid or expired session",
    })

    def _error(self, exc):
        if isinstance(exc, PermissionError):
            message = str(exc) or "Access denied"
            status = 401 if message.strip().lower() in self._UNAUTHENTICATED_ERRORS else 403
            return self._response(status, {"error": message})
        if isinstance(exc, KeyError):
            return self._response(404, {"error": str(exc).strip("'")})
        if isinstance(exc, (ValueError, TypeError)):
            return self._response(400, {"error": str(exc)})
        try:
            self.core.error_log.error("API request failed", exc)
        except Exception:
            pass
        return self._response(500, {"error": "Internal server error"})

    @classmethod
    def _auth_user_payload(cls, summary):
        """Project the login identity, mirroring FastAPI's _user_payload.

        The users table has no name column, so the display name is sourced
        from the linked customer profile when one is available.
        """
        data = summary if isinstance(summary, dict) else {}
        user = data.get("user") or {}
        customer = data.get("customer")
        urow = dict(user) if not isinstance(user, dict) else user
        payload = {}
        if customer:
            crow = dict(customer) if not isinstance(customer, dict) else customer
            name = str(crow.get("name") or "").strip()
            if name:
                payload["name"] = name
        if "email" in urow:
            payload["email"] = urow.get("email")
        return payload

    @classmethod
    def _auth_customer_payload(cls, summary):
        """Project the customer identity, mirroring FastAPI's _customer_payload."""
        data = summary if isinstance(summary, dict) else {}
        customer = data.get("customer")
        if not customer:
            return None
        crow = dict(customer) if not isinstance(customer, dict) else customer
        return {key: crow[key] for key in ("name", "email", "phone") if key in crow}

    @classmethod
    def _customer_safe_profile(cls, summary):
        """Project an account summary into customer-safe fields.

        Mirrors the FastAPI /api/v1/customer/me shape
        ({"user": {"name","email"}, "customer": {"name","email","phone"}}) so
        the WSGI routes never leak staff notes or internal profile rows.
        """
        return {
            "user": cls._auth_user_payload(summary),
            "customer": cls._auth_customer_payload(summary),
        }

    @classmethod
    def _project_auth_response(cls, result, include_customer=True):
        """Project a raw auth.login() result into the FastAPI auth shape.

        login/register return {"token","expires_at","user":...,"customer":...};
        pass include_customer=False for team-login, whose user projection is
        {"name","email","account_type","role"} with no customer block.
        """
        summary = (result or {}).get("user") or {}
        user = summary.get("user") or {}
        urow = dict(user) if not isinstance(user, dict) else user
        if include_customer:
            projected_user = cls._auth_user_payload(summary)
        else:
            projected_user = {key: urow[key] for key in ("name", "email", "account_type", "role") if key in urow}
        payload = {
            "token": (result or {}).get("token"),
            "expires_at": (result or {}).get("expires_at"),
            "user": projected_user,
        }
        if include_customer:
            payload["customer"] = cls._auth_customer_payload(summary)
        return payload

    def _public_product(self, row, storefront=None):
        """Project a product row for the customer catalog.

        Mirrors fabos_core.api._public_product exactly: picked base fields,
        storefront title/description overrides, image URLs served by the
        /api/v1/catalog/{id}/images/{iid} route, projected variants, and
        storefront metadata.
        """
        if row is None:
            return None
        data = dict(row)
        item = {key: data[key] for key in ("id", "sku", "name", "description", "category", "subcategory", "active") if key in data}
        item["price"] = round(int(data.get("price_cents") or 0) / 100, 2)
        if storefront:
            if storefront.get("customer_title"):
                item["name"] = storefront["customer_title"]
            if storefront.get("customer_description"):
                item["description"] = storefront["customer_description"]
        product_id = data.get("id")
        images = []
        for image in (self.core.products.images(product_id) or []):
            # Tolerate a missing alt_text column on older databases instead
            # of raising on products with images (mirrors fabos_core.api).
            img = dict(image) if not isinstance(image, dict) else image
            images.append({
                "id": img.get("id"),
                "url": "/api/%s/catalog/%s/images/%s" % (self.VERSION, product_id, img.get("id")),
                "is_primary": bool(img.get("is_primary")),
                "alt_text": img.get("alt_text"),
            })
        item["images"] = images
        item["variants"] = [
            {key: variant[key] for key in ("id", "name", "material", "color", "price_cents", "active") if key in variant}
            for variant in [dict(candidate) for candidate in (self.core.products.variants(product_id) or [])]
        ]
        item["storefront"] = {
            "origin": storefront.get("origin_type", "catalog_import") if storefront else "catalog_import",
            "model_file_count": storefront.get("model_file_count", 0) if storefront else 0,
        }
        return item

    def _operations_dashboard(self, user):
        from datetime import datetime, timedelta
        now=datetime.now(); today=now.date().isoformat(); month_start=(now.date()-timedelta(days=29)).isoformat()
        with self.core.database.connect() as conn:
            def scalar(sql,args=()): return conn.execute(sql,args).fetchone()[0] or 0
            orders_today=int(scalar("SELECT COUNT(*) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')",(today,)))
            sales_today=int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)=date(?) AND status NOT IN ('cancelled')",(today,)))
            sales_30d=int(scalar("SELECT COALESCE(SUM(total_cents),0) FROM orders WHERE date(created_at)>=date(?) AND status NOT IN ('cancelled')",(month_start,)))
            active_orders=int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped')"))
            active_jobs=int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('queued','scheduled','printing','paused')"))
            printing_jobs=int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status IN ('printing','paused')"))
            failed_jobs=int(scalar("SELECT COUNT(*) FROM print_jobs WHERE status='failed'"))
            printer_total=int(scalar("SELECT COUNT(*) FROM printers")); printer_online=int(scalar("SELECT COUNT(*) FROM printers WHERE lower(COALESCE(status,'')) NOT IN ('offline','error')"))
            low_threshold=float(self.core.shop_settings.get("filament_low_threshold_g","250") or 250)
            low_filament=int(scalar("SELECT COUNT(*) FROM filament_spools WHERE active=1 AND remaining_g<?",(low_threshold,)))
            low_supplies=int(scalar("SELECT COUNT(*) FROM supply_items WHERE active=1 AND quantity<=low_threshold"))
            open_quotes=int(scalar("SELECT COUNT(*) FROM quotes WHERE status IN ('draft','sent')")); unpaid=int(scalar("SELECT COUNT(*) FROM invoices WHERE status IN ('open','partial')"))
            overdue=int(scalar("SELECT COUNT(*) FROM orders WHERE status NOT IN ('completed','cancelled','shipped') AND due_at IS NOT NULL AND due_at<?",(today,)))
            pending_qc=int(scalar("SELECT COUNT(*) FROM qc_inspections WHERE status='pending'"))
            recent_orders=[dict(x) for x in conn.execute("SELECT o.id,o.order_number,o.status,o.total_cents,o.due_at,o.created_at,COALESCE(c.name,'No customer') customer_name FROM orders o LEFT JOIN customers c ON c.id=o.customer_id ORDER BY o.created_at DESC LIMIT 8").fetchall()]
            jobs=[dict(x) for x in conn.execute("SELECT j.id,j.status,j.estimated_minutes,j.print_time_left_seconds,COALESCE(p.name,'Custom Job') product_name,COALESCE(pr.name,'Unassigned') printer_name,COALESCE(o.order_number,'Personal') order_number,COALESCE(fs.material || ' ' || COALESCE(fs.color,''),'No spool') spool_name FROM print_jobs j LEFT JOIN products p ON p.id=j.product_id LEFT JOIN printers pr ON pr.id=j.printer_id LEFT JOIN orders o ON o.id=j.order_id LEFT JOIN filament_spools fs ON fs.id=j.spool_id WHERE j.status IN ('queued','scheduled','printing','paused','failed') ORDER BY CASE j.status WHEN 'failed' THEN 0 WHEN 'printing' THEN 1 WHEN 'paused' THEN 2 ELSE 3 END,j.created_at LIMIT 12").fetchall()]
            printers=[dict(x) for x in conn.execute("SELECT id,name,model,status,connection_mode,simulation_progress,nozzle_temp,bed_temp,print_time_seconds,print_time_left_seconds,octoprint_state_text,octoprint_current_file,last_seen_at,total_hours FROM printers ORDER BY name").fetchall()]
            spools=[dict(x) for x in conn.execute("SELECT id,material,brand,color,remaining_g,initial_g,cost_cents,location FROM filament_spools WHERE active=1 AND remaining_g<? ORDER BY remaining_g LIMIT 10",(low_threshold,)).fetchall()]
            maintenance=[dict(x) for x in conn.execute("SELECT p.id,p.name,p.total_hours,COALESCE(MAX(m.printer_hours),0) last_service_hours,p.total_hours-COALESCE(MAX(m.printer_hours),0) hours_since_service FROM printers p LEFT JOIN maintenance_records m ON m.printer_id=p.id GROUP BY p.id ORDER BY hours_since_service DESC").fetchall()]
        try: actions=[dict(x) for x in self.core.operations.action_items()[:20]]
        except Exception: actions=[]
        return {"generated_at":now.isoformat(timespec="seconds"),"viewer":{"id":user["id"],"account_type":user.get("account_type"),"role":user.get("role")},"business":{"orders_today":orders_today,"sales_today_cents":sales_today,"sales_30d_cents":sales_30d,"active_orders":active_orders,"open_quotes":open_quotes,"unpaid_invoices":unpaid,"overdue_orders":overdue,"pending_qc":pending_qc},"production":{"active_jobs":active_jobs,"printing_jobs":printing_jobs,"failed_jobs":failed_jobs,"jobs":jobs},"printers":{"total":printer_total,"online":printer_online,"items":printers},"inventory":{"low_filament":low_filament,"low_supplies":low_supplies,"filament_threshold_g":low_threshold,"spools":spools},"maintenance":{"items":maintenance},"recent_orders":recent_orders,"action_items":actions}

    def request(self, method, path, body=None, headers=None, raw_body=None):
        method = (method or "GET").upper()
        parsed = urlsplit(path or "/")
        route = [p for p in parsed.path.strip("/").split("/") if p]
        query = parse_qs(parsed.query, keep_blank_values=True)
        body = body or {}
        try:
            if route == ["api", self.VERSION, "health"] and method == "GET":
                return self._response(200, {"ok": True, "service": "FabOS", "api_version": self.VERSION})

            if route == ["api", self.VERSION, "admin", "operations", "dashboard"] and method == "GET":
                context=self._context(headers, "production.read")
                return self._response(200, self._operations_dashboard(context))

            if route == ["api", self.VERSION, "catalog"] and method == "GET":
                rows = self.core.products.customer_catalog(
                    query.get("q", [""])[0], query.get("category", ["All"])[0],
                    query.get("sort", ["name"])[0],
                    query.get("desc", ["0"])[0] not in ("0", "false", "no"),
                )
                return self._response(200, {"products": [self._public_product(row, storefront) for row, storefront in rows]})

            if route == ["api", self.VERSION, "catalog", "categories"] and method == "GET":
                rows = self.core.products.customer_catalog()
                categories = sorted({str(row["category"] or "Other") for row, _readiness in rows if str(row["category"] or "").strip()})
                return self._response(200, {"categories": categories})

            if len(route) == 4 and route[:3] == ["api", self.VERSION, "catalog"] and method == "GET":
                product = self.core.products.get(route[3])
                if product is None or not self.core.products.is_customer_eligible(route[3]):
                    raise KeyError("Product not found")
                return self._response(200, self._public_product(product, self.core.products.storefront_state(route[3])))

            if len(route) == 6 and route[:3] == ["api", self.VERSION, "catalog"] and route[4] == "images" and method == "GET":
                # File-serving route mirroring fabos_core.api:catalog_product_image,
                # with the same traversal guard: the resolved file must stay
                # inside the project root or the configured data directory.
                product_id, image_id = route[3], route[5]
                product = self.core.products.get(product_id)
                if product is None or not self.core.products.is_customer_eligible(product_id):
                    raise KeyError("Product not found")
                with self.core.database.connect() as conn:
                    image = conn.execute(
                        "SELECT path FROM product_images WHERE id=? AND product_id=?",
                        (image_id, product_id),
                    ).fetchone()
                if not image:
                    raise KeyError("Image not found")
                raw = str(image["path"] or "").replace("\\", "/").strip()
                if not raw or raw.lower().startswith(("http://", "https://", "data:")):
                    raise KeyError("Image file not available")
                project_root = Path(__file__).resolve().parents[1]
                settings = getattr(self.core, "settings", None)
                data_dir = getattr(settings, "data_dir", None) if settings else None
                candidates = []
                path = Path(raw)
                if path.is_absolute():
                    candidates.append(path)
                else:
                    candidates.append(project_root / raw)
                    candidates.append(project_root / "data" / raw)
                    if data_dir:
                        candidates.append(Path(str(data_dir)) / raw)
                    if raw.startswith("Catalog_Images/"):
                        candidates.append(project_root / "data" / "catalog" / raw)
                allowed_roots = [project_root.resolve()]
                if data_dir:
                    allowed_roots.append(Path(str(data_dir)).resolve())
                target = None
                for candidate in candidates:
                    try:
                        resolved = candidate.resolve()
                        if not resolved.is_file():
                            continue
                        if not any(os.path.commonpath([str(resolved), str(root)]) == str(root) for root in allowed_roots):
                            continue
                        target = resolved
                        break
                    except (OSError, ValueError):
                        continue
                if target is None:
                    raise KeyError("Image file not available")
                # Binary escape hatch: served inline (not as an attachment) so
                # <img> tags and the storefront can render it directly.
                return {
                    "status": 200,
                    "data": {"_wsgi_file": {
                        "bytes": target.read_bytes(),
                        "filename": target.name,
                        "content_type": mimetypes.guess_type(target.name)[0] or "application/octet-stream",
                        "disposition": "inline",
                    }},
                }

            if route == ["api", self.VERSION, "auth", "login"] and method == "POST":
                client_ip = _rate_limit_client_ip(headers)
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
                    return self._response(200, self._project_auth_response(result))
                return self._response(401, {"error": "Invalid email/username or password"})

            if route == ["api", self.VERSION, "auth", "team-login"] and method == "POST":
                allowed, retry_after = self._allow_public_attempt("team_login", _rate_limit_client_ip(headers))
                if not allowed:
                    return self._response(429, {"error": "Too many team sign-in attempts. Please try again later.", "retry_after": retry_after})
                result = self.core.auth.login(body.get("identifier", ""), body.get("password", ""))
                if not result:
                    return self._response(401, {"error": "Invalid credentials"})
                account = result.get("user", {}).get("user", {}) if isinstance(result.get("user"), dict) else {}
                if str(account.get("account_type") or "").lower() not in {"employee", "administrator"}:
                    self.core.auth.logout(result.get("token", ""))
                    return self._response(403, {"error": "A team or administrator account is required"})
                return self._response(200, self._project_auth_response(result, include_customer=False))

            if route == ["api", self.VERSION, "auth", "logout"] and method == "POST":
                # Idempotent like the FastAPI route: logging out without a
                # token (or with an already-dead one) still reports success.
                token = self._auth_token(headers)
                if token:
                    self.core.auth.logout(token)
                return self._response(200, {"logged_out": True})

            if route == ["api", self.VERSION, "me"] and method == "GET":
                context = self._context(headers)
                return self._response(200, self._customer_safe_profile(self.core.accounts.account_summary(context["id"])))

            if route == ["api", self.VERSION, "customer", "me"] and method == "GET":
                context = self._context(headers)
                return self._response(200, self._customer_safe_profile(self.core.accounts.account_summary(context["id"])))

            if route == ["api", self.VERSION, "customer", "me"] and method == "PATCH":
                context = self._context(headers)
                customer = self.core.accounts.customer_for_user(context["id"])
                if not customer:
                    raise PermissionError("Customer account is not linked")
                allowed = {"name", "email", "phone"}
                payload = {key: body.get(key) for key in allowed if key in body and body.get(key) is not None}
                if "email" in payload:
                    # Mirror the FastAPI update_me validation: malformed
                    # emails are a 400, duplicates are a 409, and the login
                    # identifier in users stays in sync with the profile.
                    email = str(payload["email"] or "").strip().lower()
                    if not email or "@" not in email:
                        raise ValueError("A valid email is required")
                    existing = self.core.accounts.get_by_email(email)
                    if existing and str(existing["id"]) != str(context["id"]):
                        return self._response(409, {"error": "An account with that email already exists"})
                    payload["email"] = email
                    try:
                        self.core.accounts.update_account(context["id"], email=email)
                    except ValueError as exc:
                        return self._response(409, {"error": str(exc)})
                if payload:
                    self.core.customers.save(payload, customer["id"])
                return self._response(200, self._customer_safe_profile(self.core.accounts.account_summary(context["id"])))

            if route == ["api", self.VERSION, "customer", "quotes"] and method == "POST":
                context = self._context(headers)
                quote, items = self.core.customer_commerce.create_quote_request(context["id"], body.get("project") or body)
                return self._response(201, {"quote": quote, "items": items, "quote_number": quote["quote_number"]})

            if route == ["api", self.VERSION, "customer", "quotes", "upload"] and method == "POST":
                # Authenticated customer model upload. Mirrors the FastAPI
                # route via the shared store_customer_quote_upload core; the
                # multipart body is parsed from the raw request bytes because
                # the WSGI layer otherwise only decodes JSON.
                from fabos_core.services.customer_api_writes import store_customer_quote_upload
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                parsed = _parse_multipart(raw_body, (headers or {}).get("Content-Type", ""))
                if parsed is None:
                    raise ValueError("Expected a multipart/form-data request")
                fields, files = parsed
                if "file" not in files:
                    raise ValueError("A model file is required")
                filename, file_bytes = files["file"]
                try:
                    result = store_customer_quote_upload(
                        self.core,
                        context["id"],
                        idea=fields.get("idea", ""),
                        dimensions=fields.get("dimensions", ""),
                        material=fields.get("material", ""),
                        quantity=fields.get("quantity", 1),
                        notes=fields.get("notes", ""),
                        cad_job_id=fields.get("cad_job_id") or None,
                        filename=filename,
                        file_bytes=file_bytes,
                    )
                except Exception as exc:
                    # The shared core raises fastapi.HTTPException; map it to
                    # the WSGI status shape without importing fastapi here.
                    status = getattr(exc, "status_code", None)
                    if isinstance(status, int):
                        return self._response(status, {"error": getattr(exc, "detail", str(exc)) or "Upload failed"})
                    raise
                return self._response(201, result)

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
                orders = []
                for row in self.core.orders.list_for_user(context["id"]):
                    data = dict(row)
                    data["status"] = _CUSTOMER_STATUS.get(str(data.get("status") or "new").lower(), "Order received")
                    orders.append(data)
                return self._response(200, {"orders": orders})

            if len(route) == 5 and route[:4] == ["api", self.VERSION, "customer", "orders"] and method == "GET":
                context = self._context(headers)
                order, items = self.core.orders.get_for_user(context["id"], route[4])
                order_data = dict(order)
                order_data["status"] = _CUSTOMER_STATUS.get(str(order_data.get("status") or "new").lower(), "Order received")
                dossier = self.core.orders.dossier(route[4])
                designs = [
                    {key: design[key] for key in ("id", "name", "current_version", "design_version", "design_version_label") if key in design}
                    for design in [dict(candidate) for candidate in (dossier.get("designs") or [])]
                ]
                return self._response(200, {"order": order_data, "items": items, "designs": designs})

            if len(route) == 6 and route[:4] == ["api", self.VERSION, "customer", "orders"] and route[5] == "payment-session" and method == "POST":
                context = self._context(headers)
                payment = self.core.payments.create_checkout(context["id"], route[4])
                # Mirror the FastAPI projection: (status, checkout_url) only —
                # never the full payment_transactions row.
                row = dict(payment) if not isinstance(payment, dict) else payment
                projected = {key: row[key] for key in ("status", "checkout_url") if key in row}
                return self._response(200, {"payment": projected, **projected})

            # Customer quote/proof workflow (mirrors the FastAPI routes in
            # fabos_core/api.py + fabos_core/services/design_proofs_api.py so
            # WSGI deployments serve the same customer surface).
            if len(route) == 6 and route[:4] == ["api", self.VERSION, "customer", "quotes"] and route[5] == "accept" and method == "POST":
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                quote_id = route[4]
                try:
                    row, _items = self.core.quotes.get_for_user(context["id"], quote_id)
                    status = str(row["status"] or "").lower()
                    if status == "approved":
                        existing = self.core.quotes.convert_to_order(quote_id)
                        return self._response(200, {"accepted": True, "order_id": existing})
                    if status != "sent":
                        return self._response(409, {"error": "This quote is not ready for customer acceptance."})
                    expires = str(row["expires_at"] or "").strip()
                    if expires and expires[:10] < datetime.utcnow().date().isoformat():
                        self.core.quotes.set_status(quote_id, "expired")
                        return self._response(409, {"error": "This quote has expired. Please contact FABVEX for an updated quote."})
                    self.core.quotes.set_status(quote_id, "accepted")
                    order_id = self.core.quotes.convert_to_order(quote_id)
                    return self._response(200, {"accepted": True, "order_id": order_id})
                except PermissionError:
                    return self._response(403, {"error": "Quote access denied"})
                except KeyError:
                    return self._response(404, {"error": "Quote not found"})
                except ValueError as exc:
                    return self._response(409, {"error": str(exc)})

            if len(route) == 6 and route[:4] == ["api", self.VERSION, "customer", "quotes"] and route[5] == "decline" and method == "POST":
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                quote_id = route[4]
                try:
                    row, _items = self.core.quotes.get_for_user(context["id"], quote_id)
                    if str(row["status"] or "").lower() != "sent":
                        return self._response(409, {"error": "This quote cannot be declined in its current state."})
                    self.core.quotes.set_status(quote_id, "declined")
                    return self._response(200, {"declined": True, "quote_id": quote_id})
                except PermissionError:
                    return self._response(403, {"error": "Quote access denied"})
                except KeyError:
                    return self._response(404, {"error": "Quote not found"})

            if route == ["api", self.VERSION, "customer", "proofs"] and method == "GET":
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                return self._response(200, {"proofs": self.core.design_proofs.list_for_customer(context["id"])})

            if len(route) == 5 and route[:4] == ["api", self.VERSION, "customer", "proofs"] and method == "GET":
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                try:
                    proof = self.core.design_proofs.get_for_customer(context["id"], route[4])
                except KeyError:
                    return self._response(404, {"error": "Design proof not found."})
                return self._response(200, {"proof": proof})

            if len(route) == 6 and route[:4] == ["api", self.VERSION, "customer", "proofs"] and route[5] == "approve" and method == "POST":
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                comment = str((body or {}).get("comment") or "")
                if len(comment) > 4000:
                    raise ValueError("Comment must be at most 4000 characters.")
                try:
                    proof = self.core.design_proofs.approve(context["id"], route[4], comment)
                except KeyError:
                    return self._response(404, {"error": "Design proof not found."})
                except ValueError as exc:
                    return self._response(409, {"error": str(exc)})
                return self._response(200, {"proof": self.core.design_proofs._public(proof)})

            if len(route) == 6 and route[:4] == ["api", self.VERSION, "customer", "proofs"] and route[5] == "request-changes" and method == "POST":
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                comment = str((body or {}).get("comment") or "")
                if len(comment) > 4000:
                    raise ValueError("Comment must be at most 4000 characters.")
                try:
                    proof = self.core.design_proofs.request_changes(context["id"], route[4], comment)
                except KeyError:
                    return self._response(404, {"error": "Design proof not found."})
                except ValueError as exc:
                    return self._response(400, {"error": str(exc)})
                return self._response(200, {"proof": self.core.design_proofs._public(proof)})

            if len(route) == 6 and route[:4] == ["api", self.VERSION, "customer", "proofs"] and route[5] == "file" and method == "GET":
                context = self._context(headers)
                if context.get("account_type") != "customer":
                    raise PermissionError("Customer account required")
                try:
                    self.core.design_proofs.get_for_customer(context["id"], route[4])
                    row = self.core.design_proofs._row(route[4])
                except KeyError:
                    return self._response(404, {"error": "Design proof not found."})
                if not row["stored_path"]:
                    return self._response(404, {"error": "This proof has no review file."})
                path = Path(str(row["stored_path"])).resolve()
                root = Path(str(self.core.design_vault.root)).resolve()
                try:
                    inside = os.path.commonpath([str(path), str(root)]) == str(root)
                except ValueError:
                    inside = False
                if not inside or not path.is_file():
                    return self._response(404, {"error": "Proof file is unavailable."})
                filename = str(row["original_name"] or path.name)
                content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
                # Binary escape hatch: create_wsgi_app serves _wsgi_file payloads
                # as raw bytes instead of JSON (the frontend fetches this as a blob).
                return {
                    "status": 200,
                    "data": {"_wsgi_file": {
                        "bytes": path.read_bytes(),
                        "filename": filename,
                        "content_type": content_type,
                    }},
                }

            if route == ["api", self.VERSION, "auth", "register"] and method == "POST":
                allowed, retry_after = self._allow_public_attempt("register", _rate_limit_client_ip(headers))
                if not allowed:
                    return self._response(429, {"error": "Too many registration attempts. Please try again later.", "retry_after": retry_after})
                result = self.core.customer_commerce.register_customer(
                    body.get("name", ""), body.get("email", ""), body.get("password", ""), body.get("phone", "")
                )
                return self._response(201, self._project_auth_response(result))

            if route == ["api", self.VERSION, "quote-requests"] and method == "POST":
                allowed, retry_after = self._allow_public_attempt("quote", _rate_limit_client_ip(headers))
                if not allowed:
                    return self._response(429, {"error": "Too many quote requests. Please try again later.", "retry_after": retry_after})
                file_bytes = None
                file_base64 = body.get("file_base64") or ""
                if file_base64:
                    # Uploads require an account; the text-only quote form
                    # stays public. Raises 401 when no valid session is sent.
                    self._context(headers)
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

            if len(route) == 5 and route[:4] == ["api", self.VERSION, "webhooks", "payments"] and method == "POST":
                # Provider webhook receiver. Mirrors the FastAPI route: no
                # customer auth (the provider signature is the credential), so
                # the RAW body bytes must reach handle_webhook untouched —
                # signature verification fails on re-serialized JSON.
                from fabos_core.services.payment_api import _record_refund
                from fabos_core.services.payments import PaymentProviderError, PaymentProviderNotConfigured
                provider = str(route[4] or "").strip().lower()
                if provider == "stripe":
                    signature = (headers or {}).get("Stripe-Signature", "")
                else:
                    signature = (headers or {}).get("X-Square-Hmacsha256-Signature", "")
                payload = raw_body or b""
                try:
                    result = self.core.payments.handle_webhook(payload, signature, provider)
                    refund = _record_refund(self.core, provider, payload)
                    if refund:
                        result["refund"] = refund
                    return self._response(200, result)
                except PaymentProviderNotConfigured as exc:
                    return self._response(503, {"error": str(exc)})
                except PaymentProviderError as exc:
                    return self._response(400, {"error": str(exc)})

            # Admin-workspace, customer CAD, and remaining customer routes live
            # in fabos_api/wsgi_extended.py so this dispatcher stays readable;
            # they mirror the FastAPI routes via the same core services.
            extended = handle_extended_routes(self, method, route, query, body, headers, raw_body)
            if extended is not None:
                return extended

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
                   "X-Forwarded-For": environ.get("HTTP_X_FORWARDED_FOR", ""),
                   "X-Direct-Peer": environ.get("REMOTE_ADDR", ""),
                   "Content-Type": environ.get("CONTENT_TYPE", ""),
                   "Stripe-Signature": environ.get("HTTP_STRIPE_SIGNATURE", ""),
                   "X-Square-Hmacsha256-Signature": environ.get("HTTP_X_SQUARE_HMACSHA256_SIGNATURE", "")}
        result = api.request(environ.get("REQUEST_METHOD", "GET"), environ.get("PATH_INFO", "/") + (("?" + environ["QUERY_STRING"]) if environ.get("QUERY_STRING") else ""), body, headers, raw_body=raw)
        data = result["data"]
        if isinstance(data, dict) and "_wsgi_file" in data:
            # Binary escape hatch used by the proof-file and catalog-image
            # routes: serve the raw bytes instead of JSON so the frontend can
            # fetch them as a blob. Images are served inline so <img> tags
            # render them; everything else defaults to an attachment.
            info = data["_wsgi_file"] or {}
            payload = info.get("bytes") or b""
            filename = os.path.basename(str(info.get("filename") or "file")).replace('"', "").replace("\r", "").replace("\n", "")
            content_type = str(info.get("content_type") or "application/octet-stream")
            disposition = str(info.get("disposition") or "attachment")
            start_response("200 OK", [("Content-Type", content_type),
                                      ("Content-Disposition", '%s; filename="%s"' % (disposition, filename)),
                                      ("Cache-Control", "no-store"),
                                      ("Content-Length", str(len(payload)))])
            return [payload]
        payload = json.dumps(data, default=str).encode("utf-8")
        status_text = {
            200: "OK", 201: "Created",
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden", 404: "Not Found",
            409: "Conflict", 413: "Content Too Large", 415: "Unsupported Media Type",
            429: "Too Many Requests",
            500: "Internal Server Error", 502: "Bad Gateway", 503: "Service Unavailable",
        }.get(result["status"], "OK")
        start_response("%d %s" % (result["status"], status_text), [("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "no-store"), ("Content-Length", str(len(payload)))])
        return [payload]

    return application
