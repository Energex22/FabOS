"""HTTP API boundary for the customer-facing web application.

The API delegates business rules to the existing internal services. It intentionally
serializes only customer-safe fields and never exposes the internal order dossier.
Administrator routes are separately protected and are not part of the customer UI.
"""

import json
import base64
import os
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import re
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fabos_core.services.rate_limit import RateLimiter, request_client_key
from fabos_core.services.shop_settings import resolve_quote_validity_days
from pydantic import BaseModel, Field
from fabos_core.services.cad_generation import CadGenerationError

from fabos_core.application import FabOSApplication
from fabos_core.services.admin_api import register_admin_routes
from fabos_core.services.customer_api_writes import register_customer_write_routes
from fabos_core.services.design_proofs_api import register_design_proof_routes
from fabos_core.services.payment_api import register_payment_routes
from fabos_core.services.customer_notifications import (
    CustomerNotificationService, normalize_notification_preference)
from fabos_core.services.fulfillment import FulfillmentService


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


def _user_payload(user: Any, customer: Any = None) -> Dict[str, Any]:
    """Project the login identity.

    The users table has no name column, so the display name is sourced from
    the linked customer profile when one is available.
    """
    payload = _pick(user, ("name", "email"))
    if "name" not in payload and customer:
        name = str((_json(customer) or {}).get("name") or "").strip()
        if name:
            payload = {"name": name, **payload}
    return payload


def _customer_payload(customer: Any) -> Optional[Dict[str, Any]]:
    if not customer:
        return None
    payload = _pick(customer, ("name", "email", "phone"))
    try:
        payload["notification_preference"] = normalize_notification_preference(
            customer["notification_preference"])
    except (KeyError, IndexError, TypeError):
        payload["notification_preference"] = "email"
    return payload


def _notification_payload(row: Any) -> Dict[str, Any]:
    payload = _pick(row, ("id", "event_type", "entity_type", "entity_id",
                          "title", "body", "deep_link", "channels_json", "created_at"))
    try:
        payload["is_read"] = bool(int(row["is_read"]))
    except (KeyError, IndexError, TypeError, ValueError):
        payload["is_read"] = False
    return payload


def _quote_payload(row: Any) -> Dict[str, Any]:
    return _pick(row, ("id", "quote_number", "status", "notes", "created_at", "updated_at", "total_cents", "expires_at"))


def _quote_item_payload(item: Any) -> Dict[str, Any]:
    return _pick(item, ("id", "description", "quantity", "unit_price_cents", "material", "color", "estimated_minutes", "estimated_filament_g"))


def _order_payload(row: Any) -> Dict[str, Any]:
    return _pick(row, ("id", "order_number", "status", "created_at", "updated_at", "total_cents", "shipping_cents", "tax_cents", "shipping_address_json", "checkout_notes", "quote_id"))


def _order_item_payload(item: Any) -> Dict[str, Any]:
    return _pick(item, ("id", "product_name", "description", "quantity", "unit_price_cents", "material", "color"))


def _customer_design_payload(design: Any) -> Dict[str, Any]:
    return _pick(design, ("id", "name", "current_version", "design_version", "design_version_label"))


def _payment_payload(payment: Any) -> Dict[str, Any]:
    return _pick(payment, ("status", "checkout_url"))


_REFERENCE_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp"}


def _sniff_reference_image_type(raw: bytes) -> Optional[str]:
    """Detect a reference image's true type from magic bytes.

    The client-supplied Content-Type header is not trustworthy; a non-image
    with a spoofed header must not be base64-embedded and sent to the AI
    service. Returns the canonical MIME type or None if unrecognized.
    """
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if raw[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if raw[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return "image/webp"
    return None


def _public_product(row: Any, application: FabOSApplication, storefront: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    raw = _json(row) or {}
    item = _pick(raw, ("id", "sku", "name", "description", "category", "subcategory", "active"))
    item["price"] = round(int(raw.get("price_cents") or 0) / 100, 2)
    if storefront:
        if storefront.get("customer_title"):
            item["name"] = storefront["customer_title"]
        if storefront.get("customer_description"):
            item["description"] = storefront["customer_description"]
    item["images"] = []
    for image in application.products.images(row["id"]):
        # The product_images table has no alt_text column on older databases;
        # tolerate its absence instead of raising on products with images.
        img = dict(image)
        item["images"].append({
            "id": img["id"],
            "url": "/api/v1/catalog/%s/images/%s" % (row["id"], img["id"]),
            "is_primary": bool(img["is_primary"]),
            "alt_text": img.get("alt_text"),
        })
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
    notification_preference: Optional[str] = Field(default=None, max_length=10)


class LoginRequest(BaseModel):
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=1024)


class CadGenerationRequest(BaseModel):
    prompt: Optional[str] = Field(default=None, max_length=12000)
    spec: Optional[Dict[str, Any]] = None
    output_formats: List[str] = Field(default_factory=lambda: ["stl", "step", "3mf"])
    printer_id: Optional[str] = Field(default=None, max_length=128)

class CadRevisionRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=8000)
    output_formats: List[str] = Field(default_factory=lambda: ["stl", "step"])

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
    # CAD generation and vision analysis can be CPU/API intensive. Keep a
    # per-customer limiter separate from login/public traffic.
    app.state.cad_rate_limiter = RateLimiter(20, 300)

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
        result = application.auth.login(
            payload.identifier,
            payload.password,
            ip_address=client,
            user_agent=(request.headers.get("user-agent") or "")[:1000],
        )
        if not result:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        summary = result["user"]
        return {"token": result["token"], "expires_at": result["expires_at"], "user": _user_payload(summary["user"], summary.get("customer")), "customer": _customer_payload(summary.get("customer"))}

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
        result = application.auth.login(
            payload.identifier,
            payload.password,
            ip_address=client,
            user_agent=(request.headers.get("user-agent") or "")[:1000],
        )
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

    @app.get("/api/v1/customer/cad/capabilities")
    def customer_cad_capabilities(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        return application.cad_generation.capabilities()

    @app.get("/api/v1/customer/cad/printers")
    def customer_cad_printers(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        return {"printers": application.cad_generation.list_printers()}

    def allow_customer_cad(user: Any, operation: str) -> None:
        key = "cad:%s:%s" % (str(user["id"]), operation)
        if not app.state.cad_rate_limiter.allow(key):
            raise HTTPException(
                status_code=429,
                detail="CAD request limit reached. Try again later.",
                headers={"Retry-After": str(app.state.cad_rate_limiter.retry_after(key))},
            )

    @app.post("/api/v1/customer/cad/generate")
    def customer_cad_generate(payload: CadGenerationRequest, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        allow_customer_cad(user, "generate")
        if not payload.prompt and not payload.spec:
            raise HTTPException(status_code=400, detail="Provide a design prompt or structured specification")
        try:
            result = application.cad_generation.generate(
                spec=payload.spec,
                prompt=payload.prompt,
                output_formats=payload.output_formats,
                owner_id=user["id"],
            )
        except CadGenerationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="CAD generation failed") from exc
        artifacts = [
            {"format": item["format"], "bytes": item["bytes"],
             "url": "/api/v1/customer/cad/artifacts/%s/%s" % (result["job_id"], item["format"])}
            for item in result["artifacts"]
        ]
        return {"job_id": result["job_id"], "spec": result["spec"],
                "verification": result["verification"], "artifacts": artifacts}

    @app.post("/api/v1/customer/cad/analyze-reference")
    async def customer_cad_analyze_reference(
        reference_note: str = Form(default=""),
        files: List[UploadFile] = File(default=[]),
        user: Any = Depends(customer_user),
        application: FabOSApplication = Depends(get_application),
    ):
        allow_customer_cad(user, "reference")
        if not files:
            raise HTTPException(status_code=400, detail="Upload at least one reference image")
        if len(files) > 4:
            raise HTTPException(status_code=400, detail="A maximum of 4 reference images is supported")
        images = []
        for uploaded in files:
            content_type = str(uploaded.content_type or "").lower()
            if content_type not in _REFERENCE_IMAGE_TYPES:
                raise HTTPException(status_code=400, detail="Only PNG, JPEG, and WebP reference images are supported")
            raw = await uploaded.read(5 * 1024 * 1024 + 1)
            if len(raw) > 5 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Each reference image must be 5 MB or smaller")
            # Never trust the client-supplied Content-Type: verify the magic
            # bytes and embed the sniffed type, not the claimed one.
            actual_type = _sniff_reference_image_type(raw)
            if actual_type != content_type:
                raise HTTPException(status_code=400, detail="Uploaded file is not a valid %s image" % content_type.split("/", 1)[1].upper())
            images.append("data:%s;base64,%s" % (actual_type, base64.b64encode(raw).decode("ascii")))
        try:
            result = application.ai.design_spec_from_images(images, reference_note=reference_note)
            metadata = result.get("metadata") or {}
            return {
                "spec": result,
                "scale_confirmed": bool(metadata.get("scale_confirmed")),
                "scale_source": metadata.get("scale_source", "none"),
                "reference_kind": metadata.get("reference_kind", "mixed"),
                "confidence": metadata.get("confidence", 0.0),
                "missing_dimensions": metadata.get("missing_dimensions", []),
                "feature_uncertainties": metadata.get("feature_uncertainties", []),
                "needs_user_confirmation": bool(metadata.get("needs_user_confirmation")),
            }
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Reference analysis failed") from exc

    @app.post("/api/v1/customer/cad/preflight")
    def customer_cad_preflight(payload: CadGenerationRequest, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        allow_customer_cad(user, "preflight")
        if not payload.prompt and not payload.spec:
            raise HTTPException(status_code=400, detail="Provide a design prompt or structured specification")
        printer_id = payload.printer_id
        try:
            return application.cad_generation.preflight(spec=payload.spec, prompt=payload.prompt, printer_id=printer_id)
        except CadGenerationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="CAD preflight failed") from exc

    @app.post("/api/v1/customer/cad/jobs/{job_id}/revise")
    def customer_cad_revise(job_id: str, payload: CadRevisionRequest, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        allow_customer_cad(user, "revise")
        if not re.fullmatch(r"[0-9a-fA-F-]{20,80}", job_id):
            raise HTTPException(status_code=404, detail="CAD job not found")
        try:
            result = application.cad_generation.revise(
                job_id=job_id,
                instruction=payload.instruction,
                output_formats=payload.output_formats,
                owner_id=user["id"],
            )
        except CadGenerationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="CAD revision failed") from exc
        artifacts = [
            {"format": item["format"], "bytes": item["bytes"],
             "url": "/api/v1/customer/cad/artifacts/%s/%s" % (result["job_id"], item["format"])}
            for item in result["artifacts"]
        ]
        return {"job_id": result["job_id"], "spec": result["spec"],
                "verification": result["verification"], "artifacts": artifacts}

    @app.get("/api/v1/customer/cad/jobs")
    def customer_cad_jobs(limit: int = 50, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        try:
            jobs = application.cad_generation.list_jobs(user["id"], limit=limit)
            for job in jobs:
                job["artifacts"] = [
                    {"format": item.get("format"), "bytes": item.get("bytes"),
                     "url": "/api/v1/customer/cad/artifacts/%s/%s" % (job["id"], item.get("format"))}
                    for item in (job.get("artifacts") or [])
                    if item.get("format") in {"stl", "step", "3mf"}
                ]
            return {"jobs": jobs}
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid CAD history limit")

    @app.get("/api/v1/customer/cad/jobs/{job_id}")
    def customer_cad_job(job_id: str, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        if not re.fullmatch(r"[0-9a-fA-F-]{20,80}", job_id):
            raise HTTPException(status_code=404, detail="CAD job not found")
        result = application.cad_generation.get_job(job_id, owner_id=user["id"])
        if not result:
            raise HTTPException(status_code=404, detail="CAD job not found")
        result["artifacts"] = [
            {"format": item.get("format"), "bytes": item.get("bytes"),
             "url": "/api/v1/customer/cad/artifacts/%s/%s" % (job_id, item.get("format"))}
            for item in (result.get("artifacts") or [])
            if item.get("format") in {"stl", "step", "3mf"}
        ]
        return result

    @app.get("/api/v1/customer/cad/artifacts/{job_id}/{fmt}")
    def customer_cad_artifact(job_id: str, fmt: str, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        if not re.fullmatch(r"[0-9a-fA-F-]{20,80}", job_id):
            raise HTTPException(status_code=404, detail="CAD artifact not found")
        if fmt.lower() not in {"stl", "step", "3mf"}:
            raise HTTPException(status_code=404, detail="CAD artifact not found")
        root = application.cad_generation.root.resolve()
        target = (root / job_id / ("model." + fmt.lower())).resolve()
        try:
            if target.parent.parent != root or not target.is_file():
                raise HTTPException(status_code=404, detail="CAD artifact not found")
            metadata = json.loads((target.parent / "metadata.json").read_text(encoding="utf-8"))
            if str(metadata.get("owner_id") or "") != str(user["id"]):
                raise HTTPException(status_code=404, detail="CAD artifact not found")
        except HTTPException:
            raise
        except (OSError, ValueError, json.JSONDecodeError):
            raise HTTPException(status_code=404, detail="CAD artifact not found")
        return FileResponse(str(target), filename=target.name)

    @app.get("/api/v1/customer/me")
    def me(user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        customer = application.accounts.customer_for_user(user["id"])
        return {"user": _user_payload(user, customer), "customer": _customer_payload(customer)}

    @app.patch("/api/v1/customer/me")
    def update_me(payload: ProfileUpdate, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        customer = application.accounts.customer_for_user(user["id"])
        if not customer:
            raise HTTPException(status_code=409, detail="Customer account is not linked")
        values = {key: value for key, value in payload.model_dump().items() if value is not None}
        if "notification_preference" in values:
            preference = str(values["notification_preference"] or "").strip().lower()
            if preference not in {"email", "sms", "both"}:
                raise HTTPException(status_code=400, detail="notification_preference must be one of: email, sms, both")
            values["notification_preference"] = preference
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
        customer = application.accounts.customer_for_user(user["id"])
        return {"user": _user_payload(updated_user, customer), "customer": _customer_payload(customer)}

    @app.post("/api/v1/customer/quotes/{quote_id}/accept")
    def accept_customer_quote(quote_id: str, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        try:
            row, _items = application.quotes.get_for_user(user["id"], quote_id)
            status = str(row["status"] or "").lower()
            if status == "approved":
                existing = application.quotes.convert_to_order(quote_id)
                return {"accepted": True, "order_id": existing}
            if status != "sent":
                raise HTTPException(status_code=409, detail="This quote is not ready for customer acceptance.")
            expires = str(row["expires_at"] or "").strip()
            if expires and expires[:10] < datetime.utcnow().date().isoformat():
                application.quotes.set_status(quote_id, "expired")
                raise HTTPException(status_code=409, detail="This quote has expired. Please contact FABVEX for an updated quote.")
            application.quotes.set_status(quote_id, "accepted")
            order_id = application.quotes.convert_to_order(quote_id)
            return {"accepted": True, "order_id": order_id}
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Quote access denied") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Quote not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/customer/quotes/{quote_id}/decline")
    def decline_customer_quote(quote_id: str, user: Any = Depends(customer_user), application: FabOSApplication = Depends(get_application)):
        try:
            row, _items = application.quotes.get_for_user(user["id"], quote_id)
            if str(row["status"] or "").lower() != "sent":
                raise HTTPException(status_code=409, detail="This quote cannot be declined in its current state.")
            application.quotes.set_status(quote_id, "declined")
            return {"declined": True, "quote_id": quote_id}
        except HTTPException:
            raise
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="Quote access denied") from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Quote not found") from exc

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
        # Final polish: same lightweight fulfillment summary as the detail
        # endpoint, batched in one query (no N+1).
        fulfillment_service = getattr(application, "fulfillment", None)
        payloads = fulfillment_service.customer_payloads_for_orders(
            [row["id"] for row in rows]) if fulfillment_service else {}
        orders = []
        for row in rows:
            item = _order_payload(row)
            item["status"] = CUSTOMER_STATUS.get(str(row["status"] or "new").lower(), "Order received")
            item["fulfillment"] = payloads.get(str(row["id"]), FulfillmentService.customer_payload(None))
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
        dossier = application.orders.dossier(order_id)
        order["next_step"] = dossier.get("next_step")
        # Phase 4: customer-facing fulfillment / tracking card. Every key is
        # present; unknown values are null, never omitted.
        fulfillment_service = getattr(application, "fulfillment", None)
        order["fulfillment"] = FulfillmentService.customer_payload(
            fulfillment_service.get_for_order(order_id) if fulfillment_service else None)
        return {
            "order": order,
            "items": [_order_item_payload(item) for item in items],
            "designs": [_customer_design_payload(design) for design in dossier.get("designs", [])],
        }

    def _notification_customer(user: Any, application: FabOSApplication):
        customer = application.accounts.customer_for_user(user["id"])
        if not customer:
            raise HTTPException(status_code=409, detail="Customer account is not linked")
        return customer

    @app.get("/api/v1/customer/notifications")
    def customer_notifications(page: int = 1, per_page: int = 25,
                               user: Any = Depends(customer_user),
                               application: FabOSApplication = Depends(get_application)):
        customer = _notification_customer(user, application)
        service = CustomerNotificationService(application.database, application.shop_settings)
        rows, total = service.list_for_customer(customer["id"], page=page, per_page=per_page)
        return {
            "notifications": [_notification_payload(row) for row in rows],
            "page": max(1, int(page or 1)),
            "per_page": min(100, max(1, int(per_page or 25))),
            "total": total,
            "unread": service.unread_count(customer["id"]),
        }

    @app.get("/api/v1/customer/notifications/unread-count")
    def customer_notifications_unread_count(user: Any = Depends(customer_user),
                                            application: FabOSApplication = Depends(get_application)):
        customer = _notification_customer(user, application)
        service = CustomerNotificationService(application.database, application.shop_settings)
        return {"unread": service.unread_count(customer["id"])}

    @app.post("/api/v1/customer/notifications/{notification_id}/read")
    def customer_notification_read(notification_id: str, user: Any = Depends(customer_user),
                                    application: FabOSApplication = Depends(get_application)):
        customer = _notification_customer(user, application)
        service = CustomerNotificationService(application.database, application.shop_settings)
        if not service.mark_read(customer["id"], notification_id):
            raise HTTPException(status_code=404, detail="Notification not found")
        return {"read": True, "unread": service.unread_count(customer["id"])}

    @app.post("/api/v1/customer/notifications/read-all")
    def customer_notifications_read_all(user: Any = Depends(customer_user),
                                         application: FabOSApplication = Depends(get_application)):
        customer = _notification_customer(user, application)
        service = CustomerNotificationService(application.database, application.shop_settings)
        marked = service.mark_all_read(customer["id"])
        return {"read": True, "marked": marked, "unread": 0}

    @app.get("/api/v1/admin/quotes")
    def admin_quotes(q: str = "", status: str = "All", group: str = "all", user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        rows = application.quotes.list(query=q, status=status, group=group)
        return {"quotes": [_json(row) for row in rows]}

    @app.get("/api/v1/admin/quotes/{quote_id}")
    def admin_quote(quote_id: str, user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        try:
            row, items = application.quotes.get(quote_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Quote not found") from exc
        return {"quote": _json(row), "items": [_json(item) for item in items], "versions": [_json(v) for v in application.quotes.versions(quote_id)]}

    @app.put("/api/v1/admin/quotes/{quote_id}")
    def update_admin_quote(quote_id: str, payload: dict, user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        try:
            row, existing_items = application.quotes.get(quote_id)
            requested_status = str(payload.get("status") or row["status"] or "draft").lower()
            if requested_status in {"accepted", "approved", "declined"}:
                raise HTTPException(status_code=409, detail="Customer decision states can only be changed by the customer workflow.")
            items = payload.get("items")
            if not items:
                items = [dict(item) for item in existing_items]
            expires_at = payload.get("expires_at", row["expires_at"])
            if requested_status == "sent" and not expires_at:
                expires_at = (date.today() + timedelta(days=resolve_quote_validity_days(application.shop_settings))).isoformat()
            data = {"customer_id": row["customer_id"], "status": requested_status, "expires_at": expires_at, "notes": payload.get("notes", row["notes"])}
            application.quotes.save(data, items, quote_id=quote_id)
            updated, updated_items = application.quotes.get(quote_id)
            return {"quote": _json(updated), "items": [_json(item) for item in updated_items], "versions": [_json(v) for v in application.quotes.versions(quote_id)]}
        except HTTPException:
            raise
        except (KeyError, ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/admin/customers")
    def admin_customers(q: str = "", user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        return {"customers": [_json(row) for row in application.customers.list(query=q)]}

    @app.post("/api/v1/admin/customers")
    def create_admin_customer(payload: dict, user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        try:
            customer_id = application.customers.save({
                "name": str(payload.get("name") or "").strip(),
                "email": str(payload.get("email") or "").strip().lower(),
                "phone": str(payload.get("phone") or "").strip(),
                "notes": str(payload.get("notes") or "").strip(),
            })
            return {"customer_id": customer_id, "customer": _json(application.customers.get(customer_id))}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/admin/orders/{order_id}/start-production")
    def start_admin_production(order_id: str, user: Any = Depends(administrator_user), application: FabOSApplication = Depends(get_application)):
        try:
            created = application.production.create_jobs_from_order(order_id)
            return {"order_id": order_id, "jobs_created": created, "started": bool(created)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    # Invoices and fulfillments exist on the WSGI transport (fabos_api/app.py)
    # and the admin frontend calls them; mirror them here so both transports
    # serve the same surface. Permission checks mirror the WSGI _context
    # permission arguments ("payment.read" / "fulfillment.read").
    def permission_user(permission: str):
        def check(user: Any = Depends(current_user), application: FabOSApplication = Depends(get_application)):
            try:
                application.permissions.require(user["account_type"], permission, user_id=user["id"])
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
            return user
        return check

    @app.get("/api/v1/invoices")
    def invoices(q: str = "", status: str = "All", sort: str = "created", desc: bool = True,
                 user: Any = Depends(permission_user("payment.read")),
                 application: FabOSApplication = Depends(get_application)):
        rows = application.invoices.list_for_user(user["id"], q, status, sort, desc)
        return {"invoices": [_json(row) for row in rows]}

    @app.get("/api/v1/invoices/{invoice_id}")
    def invoice_detail(invoice_id: str, user: Any = Depends(permission_user("payment.read")),
                       application: FabOSApplication = Depends(get_application)):
        try:
            invoice, items, payments = application.invoices.get_for_user(user["id"], invoice_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Invoice not found") from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"invoice": _json(invoice), "items": [_json(item) for item in items],
                "payments": [_json(payment) for payment in payments]}

    @app.get("/api/v1/admin/orders/{order_id}")
    def admin_order_detail(order_id: str, user: Any = Depends(administrator_user),
                           application: FabOSApplication = Depends(get_application)):
        """Phase 3 money handoff: full admin order detail (dossier) for the web
        console's order-detail panel — quote/jobs/QC/fulfillment/invoice/payment
        state plus the machine-readable next_step, with invoice/invoice_id
        convenience keys."""
        try:
            dossier = application.orders.dossier(order_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Order not found") from exc
        invoices = dossier.get("invoices") or []
        first = invoices[0] if invoices else None
        invoice_payload = _json(first) if first else None
        payload = {key: _json(value) for key, value in dossier.items()}
        payload["invoice"] = invoice_payload
        payload["invoice_id"] = invoice_payload.get("id") if isinstance(invoice_payload, dict) else None
        return payload

    @app.post("/api/v1/admin/orders/{order_id}/invoice")
    def create_order_invoice(order_id: str, payload: Optional[dict] = None,
                             user: Any = Depends(permission_user("payment.manage")),
                             application: FabOSApplication = Depends(get_application)):
        """Phase 3 money handoff: create (or fetch) the order's invoice.

        Invoices normally auto-create when the order is created; this endpoint
        is the manual path for back-office corrections. Idempotent: returns
        the existing live invoice when one already exists."""
        try:
            due_days = None
            if isinstance(payload, dict) and payload.get("due_days") is not None:
                due_days = int(payload.get("due_days"))
            invoice_id, created = application.invoices.create_from_order_for_user(
                user["id"], order_id, due_days=due_days)
            invoice, items, payments = application.invoices.get_for_user(user["id"], invoice_id)
            return {"invoice_id": invoice_id, "created": created,
                    "invoice": _json(invoice), "items": [_json(item) for item in items],
                    "payments": [_json(payment) for payment in payments]}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/admin/invoices/{invoice_id}/payments")
    def record_invoice_payment(invoice_id: str, payload: dict,
                               user: Any = Depends(permission_user("payment.manage")),
                               application: FabOSApplication = Depends(get_application)):
        """Phase 3 money handoff: record a payment against an invoice.

        Updates the invoice paid_cents/status (open -> partial -> paid).
        Rejects overpayment and payments on void invoices with 400."""
        try:
            amount_cents = int((payload or {}).get("amount_cents", 0))
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="amount_cents must be an integer number of cents") from None
        try:
            application.invoices.record_payment_for_user(
                user["id"], invoice_id, amount_cents,
                method=str((payload or {}).get("method") or ""),
                reference=str((payload or {}).get("reference") or ""),
                notes=str((payload or {}).get("notes") or ""))
            invoice, items, payments = application.invoices.get_for_user(user["id"], invoice_id)
            return {"invoice_id": invoice_id, "recorded_cents": amount_cents,
                    "invoice": _json(invoice), "items": [_json(item) for item in items],
                    "payments": [_json(payment) for payment in payments]}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/v1/fulfillments")
    def fulfillments(user: Any = Depends(permission_user("fulfillment.read")),
                     application: FabOSApplication = Depends(get_application)):
        return {"fulfillments": [_json(row) for row in application.fulfillment.list_for_user(user["id"])]}

    @app.get("/api/v1/fulfillments/{fulfillment_id}")
    def fulfillment_detail(fulfillment_id: str, user: Any = Depends(permission_user("fulfillment.read")),
                           application: FabOSApplication = Depends(get_application)):
        try:
            row = application.fulfillment.get_for_user(user["id"], fulfillment_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Fulfillment not found") from exc
        except (PermissionError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"fulfillment": _json(row)}

    register_admin_routes(app, get_application, administrator_user)
    register_customer_write_routes(app, get_application, customer_user)
    register_design_proof_routes(app, get_application, customer_user, administrator_user)
    register_payment_routes(app, get_application, administrator_user)
    return app


app = create_app()
