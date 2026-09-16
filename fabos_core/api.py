"""HTTP API boundary for the customer-facing FabOS web application.

The API delegates business rules to the existing FabOS services. It intentionally
serializes only customer-safe fields and never exposes the internal order dossier.
"""

import os
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from fabos_core.application import FabOSApplication
from fabos_core.services.customer_api_writes import register_customer_write_routes


CUSTOMER_STATUS = {
    "new": "Order received", "pending": "Order received", "confirmed": "Order received",
    "in_production": "Preparing your order", "ready": "Final quality check",
    "shipped": "Shipping", "completed": "Delivered", "cancelled": "Cancelled",
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


def _user_payload(user: Any) -> Dict[str, Any]:
    data = _json(user)
    if not data:
        return {}
    data.pop("password_hash", None)
    return data


def _customer_payload(customer: Any) -> Optional[Dict[str, Any]]:
    return _json(customer) if customer else None


class ProfileUpdate(BaseModel):
    name: Optional[str] = Field(default=None, max_length=200)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    notes: Optional[str] = Field(default=None, max_length=4000)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


def create_app(application: Optional[FabOSApplication] = None) -> FastAPI:
    app = FastAPI(title="FabOS Customer API", version="1.0")
    fabos = application or FabOSApplication()
    app.state.fabos = fabos

    origins = [x.strip() for x in os.environ.get("FABOS_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if x.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
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

    def customer_user(user: Any = Depends(current_user)):
        if str(user["account_type"] or "").lower() != "customer":
            raise HTTPException(status_code=403, detail="Customer account required")
        return user

    @app.get("/api/v1/health")
    def health(application: FabOSApplication = Depends(get_application)):
        return {"status": "ok", "service": "FabOS Customer API", "version": "1.0"}

    @app.get("/api/v1/catalog")
    def catalog(q: str = "", category: str = "All", sort: str = "name", desc: bool = False, application: FabOSApplication = Depends(get_application)):
        rows = application.products.list(query=q, category=category, order_by=sort, descending=desc)
        products = []
        for row in rows:
            item = _json(row)
            item["price"] = round(int(row["price_cents"] or 0) / 100, 2)
            item.pop("price_cents", None)
            item["images"] = [_json(image) for image in application.products.images(row["id"])]
            item["variants"] = [_json(variant) for variant in application.products.variants(row["id"])]
            item.pop("product_files", None)
            products.append(item)
        return {"products": products}

    @app.get("/api/v1/catalog/categories")
    def catalog_categories(application: FabOSApplication = Depends(get_application)):
        return {"categories": application.products.categories()}

    @app.get("/api/v1/catalog/{product_id}")
    def catalog_product(product_id: str, application: FabOSApplication = Depends(get_application)):
        row = application.products.get(product_id)
        if not row:
            raise HTTPException(status_code=404, detail="Product not found")
        item = _json(row)
        item["price"] = round(int(row["price_cents"] or 0) / 100, 2)
        item.pop("price_cents", None)
        item["images"] = [_json(image) for image in application.products.images(product_id)]
        item["variants"] = [_json(variant) for variant in application.products.variants(product_id)]
        item.pop("product_files", None)
        return item

    @app.post("/api/v1/auth/login")
    def login(payload: LoginRequest, application: FabOSApplication = Depends(get_application)):
        result = application.auth.login(payload.identifier, payload.password)
        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        summary = result["user"]
        return {"token": result["token"], "expires_at": result["expires_at"], "user": _user_payload(summary["user"]), "customer": _customer_payload(summary.get("customer"))}

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
        if values:
            application.customers.save(values, customer_id=customer["id"])
        updated_user = application.accounts.get_user(user["id"])
        return {"user": _user_payload(updated_user), "customer": _customer_payload(application.accounts.customer_for_user(user["id"]))}

    @app.get("/api/v1/customer/quotes")
    def customer_quotes(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        rows = application.quotes.list_for_user(user["id"])
        return {"quotes": [_json(row) for row in rows]}

    @app.get("/api/v1/customer/quotes/{quote_id}")
    def customer_quote(quote_id: str, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        try:
            row, items = application.quotes.get_for_user(user["id"], quote_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Quote access denied") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Quote not found") from exc
        return {"quote": _json(row), "items": [_json(item) for item in items]}

    @app.get("/api/v1/customer/orders")
    def customer_orders(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        rows = application.orders.list_for_user(user["id"])
        orders = []
        for row in rows:
            item = _json(row)
            item["status"] = CUSTOMER_STATUS.get(str(row["status"] or "new").lower(), "Order received")
            item.pop("customer_id", None)
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
        order = _json(row)
        order["status"] = CUSTOMER_STATUS.get(str(row["status"] or "new").lower(), "Order received")
        order.pop("customer_id", None)
        safe_items = []
        for item in items:
            value = _json(item)
            value.pop("quote_id", None)
            safe_items.append(value)
        return {"order": order, "items": safe_items}

    register_customer_write_routes(app, get_application, customer_user)
    return app


app = create_app()
