"""HTTP API boundary for the customer-facing web application.

The API delegates business rules to the existing internal services. It intentionally
serializes only customer-safe fields and never exposes the internal order dossier.
Administrator routes are separately protected and are not part of the customer UI.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional, Tuple
from pathlib import Path
import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fabos_core.services.rate_limit import RateLimiter, request_client_key
from pydantic import BaseModel, Field

from fabos_core.application import FabOSApplication
from fabos_core.services.admin_api import register_admin_routes
from fabos_core.services.customer_api_writes import register_customer_write_routes
from fabos_core.services.payment_api import register_payment_routes


CUSTOMER_STATUS = {
    "new": "Order received", "pending": "Order received", "confirmed": "Order received",
    "in_production": "Preparing your order", "production": "Preparing your order",
    "ready": "Final quality check", "shipped": "Shipping", "completed": "Delivered",
    "cancelled": "Cancelled",
}


def _json(value: Any) -> Any:
    """Convert sqlite Rows and nested values into JSON-safe structures."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if hasattr(value, "keys"):
        return {str(k): _json(value[k]) for k in value.keys()}
    return str(value)


def _pick(value: Any, fields: Tuple[str, ...]) -> Dict[str, Any]:
    data = _json(value) or {}
    return {field: data[field] for field in fields if field in data}


def _user_payload(user: Any) -> Dict[str, Any]:
    return _pick(user, ("name", "email"))


def _customer_payload(customer: Any) -> Optional[Dict[str, Any]]:
    if not customer:
        return None
    return _pick(customer, ("name", "email", "phone"))


def _quote_payload(row: Any) -> Dict[str, Any]:
    return _pick(row, ("id", "quote_number", "status", "notes", "created_at", "updated_at", "total_cents"))


def _quote_item_payload(item: Any) -> Dict[str, Any]:
    return _pick(item, ("id", "description", "quantity", "unit_price_cents", "material", "color", "estimated_minutes", "estimated_filament_g"))


def _order_payload(row: Any) -> Dict[str, Any]:
    return _pick(row, ("id", "order_number", "status", "created_at", "updated_at", "total_cents", "shipping_cents", "tax_cents", "shipping_address_json", "checkout_notes"))


def _order_item_payload(item: Any) -> Dict[str, Any]:
    return _pick(item, ("id", "product_name", "description", "quantity", "unit_price_cents", "material", "color"))


def _payment_payload(payment: Any) -> Dict[str, Any]:
    return _pick(payment, ("status", "checkout_url"))


def _public_product(row: Any, application: FabOSApplication, storefront: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = _json(row) or {}
    item = _pick(raw, ("id", "sku", "name", "description", "category", "subcategory", "active"))
    item["price"] = round(int(raw.get("price_cents") or 0) / 100, 2)
    if storefront:
        if storefront.get("customer_title"):
            item["name"] = storefront["customer_title"]
        if storefront.get("customer_description"):
            item["description"] = storefront["customer_description"]
    item["images"] = [
        {
            "id": image["id"],
            "url": "/api/v1/catalog/%s/images/%s" % (row["id"], image["id"]),
            "is_primary": bool(image["is_primary"]),
            "alt_text": image["alt_text"],
        }
        for image in application.products.images(row["id"])
    ]
    item["variants"] = [_pick(variant, ("id", "name", "material", "color", "price_cents", "active")) for variant in application.products.variants(row["id"])]
    item["storefront"] = {
        "origin": storefront.get("origin_type", "catalog_import") if storefront else "catalog_import",
        "model_file_count": storefront.get("model_file_count", 0) if storefront else 0,
    }
    return item


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=4000)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class StorefrontUpdate(BaseModel):
    visibility: str = Field(default="draft", min_length=1, max_length=20)
    origin_type: str = Field(default="catalog_import", min_length=1, max_length=40)
    source_customer_id: Optional[str] = Field(default=None, max_length=100)
    customer_title: Optional[str] = Field(default=None, max_length=200)
    customer_description: Optional[str] = Field(default=None, max_length=4000)


def create_app(application: Optional[FabOSApplication] = None) -> FastAPI:
    docs_enabled = os.environ.get("FABOS_API_DOCS", "").strip().lower() in {"1", "true", "yes"}
    app = FastAPI(
        title="Customer API",
        version="1.2",
        docs_url="/docs" if docs_enabled else None,
        redoc_url="/redoc" if docs_enabled else None,
        openapi_url="/openapi.json" if docs_enabled else None,
    )
    fabos = application or FabOSApplication()
    app.state.fabos = fabos
    app.state.auth_rate_limiter = RateLimiter(10, 300)
    # Keep team/admin authentication on its own limiter so customer login
    # traffic cannot consume the security budget for privileged accounts.
    app.state.team_auth_rate_limiter = RateLimiter(10, 300)
    app.state.public_rate_limiter = RateLimiter(30, 3600)

    allowed_hosts = [x.strip() for x in os.environ.get("FABOS_ALLOWED_HOSTS", "").split(",") if x.strip()]
    if allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    origins = [x.strip() for x in os.environ.get("FABOS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Stripe-Signature", "x-square-hmacsha256-signature"],
    )

    def get_application() -> FabOSApplication:
        return app.state.fabos

    def current_user(authorization: Optional[str] = Header(default=None), application: FabOSApplication = Depends(get_application)):
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Authentication required")
        token = authorization[7:].strip()
        user = application.auth.authenticate(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        return user

    app.state.current_user = current_user

    def customer_user(user: Any = Depends(current_user)):
        if str(user["account_type"] or "").lower() != "customer":
            raise HTTPException(status_code=403, detail="Customer account required")
        return user

    def administrator_user(user: Any = Depends(current_user)):
        if str(user["account_type"] or "").lower() != "administrator":
            raise HTTPException(status_code=403, detail="Administrator account required")
        return user

    @app.get("/api/v1/health")
    def health(application: FabOSApplication = Depends(get_application)):
        return {"status": "ok", "service": "customer-api", "version": "1.2"}

    @app.get("/api/v1/catalog")
    def catalog(q: str = "", category: str = "All", sort: str = "name", desc: bool = False, application: FabOSApplication = Depends(get_application)):
        rows = application.products.customer_catalog(query=q, category=category, order_by=sort, descending=desc)
        products = [_public_product(row, application, storefront) for row, storefront in rows]
        return {"products": products}

    @app.get("/api/v1/catalog/categories")
    def catalog_categories(application: FabOSApplication = Depends(get_application)):
        rows = application.products.customer_catalog()
        return {"categories": sorted({str(row["category"]) for row, _ in rows if str(row["category"] or "").strip()})}

    @app.get("/api/v1/catalog/{product_id}")
    def catalog_product(product_id: str, application: FabOSApplication = Depends(get_application)):
        row = application.products.get(product_id)
        if not row or not application.products.is_customer_eligible(product_id):
            raise HTTPException(status_code=404, detail="Product not found")
        return _public_product(row, application, application.products.storefront_state(product_id))

    @app.get("/api/v1/catalog/{product_id}/images/{image_id}")
    def catalog_product_image(product_id: str, image_id: str, application: FabOSApplication = Depends(get_application)):
        row = application.products.get(product_id)
        if not row or not application.products.is_customer_eligible(product_id):
            raise HTTPException(status_code=404, detail="Product not found")
        with application.database.connect() as conn:
            image = conn.execute(
                "SELECT path FROM product_images WHERE id=? AND product_id=?",
                (image_id, product_id),
            ).fetchone()
        if not image:
            raise HTTPException(status_code=404, detail="Image not found")
        raw = str(image["path"] or "").replace("\\", "/").strip()
        if not raw or raw.lower().startswith(("http://", "https://", "data:")):
            raise HTTPException(status_code=404, detail="Image file not available")
        project_root = Path(__file__).resolve().parents[1]
        data_root = Path(application.settings.data_dir).resolve()
        candidates = []
        path = Path(raw)
        if path.is_absolute():
            candidates.append(path)
        else:
            candidates.extend([project_root / raw, project_root / "data" / raw, data_root / raw])
            if raw.startswith("Catalog_Images/"):
                candidates.append(project_root / "data" / "catalog" / raw)
        allowed_roots = [project_root.resolve(), data_root]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                if not resolved.is_file():
                    continue
                if not any(os.path.commonpath([str(resolved), str(root)]) == str(root) for root in allowed_roots):
                    continue
                return FileResponse(str(resolved))
            except (OSError, ValueError):
                continue
        raise HTTPException(status_code=404, detail="Image file not available")

    @app.get("/api/v1/admin/catalog")
    def admin_catalog(q: str = "", category: str = "All", sort: str = "name", desc: bool = False, user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        rows = application.products.list(query=q, category=category, order_by=sort, descending=desc)
        products = []
        for row in rows:
            state = application.products.storefront_state(row["id"])
            products.append({"product": _json(row), "storefront": state, "customer_eligible": application.products.is_customer_eligible(row["id"])})
        return {"products": products}

    @app.get("/api/v1/admin/catalog/{product_id}")
    def admin_catalog_product(product_id: str, user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        row = application.products.get(product_id)
        if not row:
            raise HTTPException(status_code=404, detail="Product not found")
        return {"product": _json(row), "storefront": application.products.storefront_state(product_id), "customer_eligible": application.products.is_customer_eligible(product_id)}

    @app.patch("/api/v1/admin/catalog/{product_id}/storefront")
    def update_storefront(product_id: str, payload: StorefrontUpdate, user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        row = application.products.get(product_id)
        if not row:
            raise HTTPException(status_code=404, detail="Product not found")
        values = payload.model_dump()
        if values["visibility"].lower() == "published":
            state = application.products.storefront_state(product_id)
            reasons = []
            if not state["has_model"]:
                reasons.append("A printable 3D model is required")
            if not state["has_price"]:
                reasons.append("A customer price greater than zero is required")
            if state["license_status"] in {"blocked", "prohibited", "commercially_prohibited", "review_required"}:
                reasons.append("The license requires review or does not allow commercial publication")
            if reasons:
                raise HTTPException(status_code=409, detail={"message": "Product is not ready to publish", "reasons": reasons})
        state = application.products.save_storefront(product_id, values)
        return {"product": _json(row), "storefront": state, "customer_eligible": application.products.is_customer_eligible(product_id)}

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, request: Request, application: FabOSApplication = Depends(get_application)):
        client = request_client_key(request)
        identifier_key = payload.identifier.strip().lower()
        limiter_keys = ("login-ip:" + client, "login-id:" + identifier_key)
        blocked = next((key for key in limiter_keys if not app.state.auth_rate_limiter.allow(key)), None)
        if blocked:
            raise HTTPException(status_code=429, detail="Too many login attempts. Try again later.", headers={"Retry-After": str(app.state.auth_rate_limiter.retry_after(blocked))})
        result = application.auth.login(payload.identifier, payload.password)
        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        summary = result["user"]
        return {"token": result["token"], "expires_at": result["expires_at"], "user": _user_payload(summary["user"]), "customer": _customer_payload(summary.get("customer"))}

    @app.post("/api/v1/auth/team-login")
    def team_login(payload: LoginRequest, request: Request, application: FabOSApplication = Depends(get_application)):
        client = request_client_key(request)
        identifier_key = payload.identifier.strip().lower()
        limiter_keys = ("team-login-ip:" + client, "team-login-id:" + identifier_key)
        blocked = next((key for key in limiter_keys if not app.state.team_auth_rate_limiter.allow(key)), None)
        if blocked:
            raise HTTPException(
                status_code=429,
                detail="Too many team login attempts. Try again later.",
                headers={"Retry-After": str(app.state.team_auth_rate_limiter.retry_after(blocked))},
            )
        result = application.auth.login(payload.identifier, payload.password)
        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        account = result["user"]["user"]
        if str(account["account_type"] or "").lower() not in {"employee", "administrator"}:
            application.auth.logout(result["token"])
            raise HTTPException(status_code=403, detail="A team or administrator account is required")
        return {"token": result["token"], "expires_at": result["expires_at"], "user": _pick(account, ("name", "email", "account_type", "role"))}

    @app.post("/api/v1/auth/logout")
    def logout(authorization: Optional[str] = Header(default=None), application: FabOSApplication = Depends(get_application)):
        if not authorization or not authorization.lower().startswith("bearer "):
            return {"logged_out": True}
        application.auth.logout(authorization[7:].strip())
        return {"logged_out": True}

    @app.get("/api/v1/customer/me")
    def me(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        customer = application.accounts.customer_for_user(user["id"])
        return {"user": _user_payload(user), "customer": _customer_payload(customer)}

    @app.patch("/api/v1/customer/me")
    def update_me(payload: ProfileUpdate, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        customer = application.accounts.customer_for_user(user["id"])
        if not customer:
            raise HTTPException(status_code=409, detail="Customer account is not linked")
        values = {key: value for key, value in payload.model_dump().items() if value is not None}
        if "email" in values:
            email = str(values["email"] or "").strip().lower()
            if not email or "@" not in email:
                raise HTTPException(status_code=400, detail="A valid email is required")
            existing = application.accounts.get_by_email(email)
            if existing and str(existing["id"]) != str(user["id"]):
                raise HTTPException(status_code=409, detail="An account with that email already exists")
            values["email"] = email
            try:
                application.accounts.update_account(user["id"], email=email)
            except ValueError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
        if values:
            try:
                application.customers.save(values, customer_id=customer["id"])
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        updated_user = application.accounts.get_user(user["id"])
        return {"user": _user_payload(updated_user), "customer": _customer_payload(application.accounts.customer_for_user(user["id"]))}

    @app.get("/api/v1/customer/quotes")
    def customer_quotes(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        rows = application.quotes.list_for_user(user["id"])
        return {"quotes": [_quote_payload(row) for row in rows]}

    @app.get("/api/v1/customer/quotes/{quote_id}")
    def customer_quote(quote_id: str, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        try:
            row, items = application.quotes.get_for_user(user["id"], quote_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Quote access denied") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Quote not found") from exc
        return {"quote": _quote_payload(row), "items": [_quote_item_payload(item) for item in items]}

    @app.get("/api/v1/customer/orders")
    def customer_orders(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        rows = application.orders.list_for_user(user["id"])
        orders = []
        for row in rows:
            item = _order_payload(row)
            item["status"] = CUSTOMER_STATUS.get(str(row["status"] or "new").lower(), "Order received")
            orders.append(item)
        return {"orders": orders}

    @app.get("/api/v1/customer/orders/{order_id}")
    def customer_order(order_id: str, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        try:
            row, items = application.orders.get_for_user(user["id"], order_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Order access denied") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc
        order = _order_payload(row)
        order["status"] = CUSTOMER_STATUS.get(str(row["status"] or "new").lower(), "Order received")
        return {"order": order, "items": [_order_item_payload(item) for item in items]}

    register_admin_routes(app, get_application, administrator_user)
    register_customer_write_routes(app, get_application, customer_user)
    register_payment_routes(app, get_application, administrator_user)
    return app


app = create_app()
