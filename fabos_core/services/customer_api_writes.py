"""Write-side HTTP handlers for customer commerce."""
from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import tempfile
import uuid
from fastapi import Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

MAX_CUSTOM_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_CUSTOM_UPLOAD_EXTENSIONS = {".stl", ".3mf", ".step", ".stp", ".obj"}


def _json(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if hasattr(value, "keys"):
        return {str(k): _json(value[k]) for k in value.keys()}
    return str(value)


def _pick(value, fields):
    data = _json(value) or {}
    return {field: data[field] for field in fields if field in data}


def _public_user(value):
    return _pick(value, ("name", "email"))


def _public_customer(value):
    return _pick(value, ("name", "email", "phone")) if value else None


def _public_quote(value):
    return _pick(value, ("id", "quote_number", "status", "notes", "created_at", "updated_at", "total_cents"))


def _public_quote_item(value):
    return _pick(value, ("id", "description", "quantity", "unit_price_cents", "material", "color", "estimated_minutes", "estimated_filament_g"))


def _public_order(value):
    return _pick(value, ("id", "order_number", "status", "created_at", "updated_at", "total_cents", "shipping_cents", "tax_cents", "shipping_address_json", "checkout_notes"))


def _public_order_item(value):
    return _pick(value, ("id", "product_name", "description", "quantity", "unit_price_cents", "material", "color"))


def _public_payment(value):
    return _pick(value, ("status", "checkout_url"))


class RegistrationRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=8, max_length=1024)
    phone: str = Field(default="", max_length=50)

class QuoteProject(BaseModel):
    idea: str = Field(min_length=1, max_length=4000)
    dimensions: str = Field(default="", max_length=1000)
    material: str = Field(default="", max_length=200)
    quantity: int = Field(default=1, ge=1, le=1000)
    notes: str = Field(default="", max_length=4000)

class QuoteRequest(BaseModel):
    project: QuoteProject
    file: Optional[Dict[str, Any]] = None

class PublicQuoteRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320)
    project: QuoteProject
    file: Optional[Dict[str, Any]] = None

class ShippingAddress(BaseModel):
    address: str = Field(min_length=1, max_length=300)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    zip: str = Field(min_length=1, max_length=20)

class OrderItem(BaseModel):
    productId: str = Field(min_length=1, max_length=200)
    variantId: Optional[str] = Field(default=None, max_length=200)
    quantity: int = Field(default=1, ge=1, le=1000)
    configuration: Optional[Dict[str, Any]] = None

class OrderRequest(BaseModel):
    items: List[OrderItem] = Field(min_length=1, max_length=100)
    shippingAddress: ShippingAddress
    notes: str = Field(default="", max_length=4000)

class CustomProductRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    sku: str = Field(default="", max_length=100)
    category: str = Field(default="Custom Designs", max_length=100)
    description: str = Field(default="", max_length=4000)
    customer_title: str = Field(default="", max_length=200)
    customer_description: str = Field(default="", max_length=4000)
    price: float = Field(gt=0, le=100000)
    hours: float = Field(default=0, ge=0, le=10000)
    filament: float = Field(default=0, ge=0, le=100000)
    license_name: str = Field(default="Customer-origin design", max_length=200)
    license_status: str = Field(default="review_required", max_length=50)
    visibility: str = Field(default="draft", max_length=20)

def register_customer_write_routes(app, get_application, current_user):
    @app.post("/api/v1/auth/register")
    def register_customer(payload: RegistrationRequest, application=Depends(get_application)):
        try:
            result = application.customer_commerce.register_customer(payload.name, payload.email, payload.password, payload.phone)
            summary = result["user"]
            return {"token": result["token"], "expires_at": result["expires_at"], "user": _public_user(summary["user"]), "customer": _public_customer(summary.get("customer"))}
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/quote-requests")
    def create_public_quote_request(payload: PublicQuoteRequest, application=Depends(get_application)):
        try:
            project = payload.project.dict()
            file_name = str((payload.file or {}).get("name") or "").strip()
            if file_name:
                project["notes"] = (project.get("notes") or "").strip()
                project["notes"] += ("\n" if project["notes"] else "") + "File: " + file_name
            existing = application.customers.list(query=payload.email.strip())
            customer_id = next((str(row["id"]) for row in existing if str(row["email"] or "").lower()==payload.email.strip().lower()), None)
            if not customer_id:
                customer_id = application.customers.save({"name":payload.name.strip(),"email":payload.email.strip().lower(),"phone":"","notes":"Public custom-work request"})
            quote_id = _create_public_quote(application, customer_id, project)
            quote=application.quotes.get(quote_id)[0]
            return {"quote":_public_quote(quote),"request_number":str(quote["quote_number"]),"file":payload.file}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/quote-requests/upload")
    async def create_public_quote_request_with_file(
        name: str = File(..., min_length=1, max_length=200),
        email: str = File(..., min_length=3, max_length=320),
        idea: str = File(..., min_length=1, max_length=4000),
        dimensions: str = File(default="", max_length=1000),
        material: str = File(default="", max_length=200),
        quantity: int = File(default=1, ge=1, le=1000),
        notes: str = File(default="", max_length=4000),
        file: UploadFile = File(...),
        application=Depends(get_application),
    ):
        filename = Path(file.filename or "").name
        extension = Path(filename).suffix.lower()
        if extension not in ALLOWED_CUSTOM_UPLOAD_EXTENSIONS:
            raise HTTPException(status_code=415, detail="Unsupported 3D model file type")
        if not filename:
            raise HTTPException(status_code=400, detail="A model filename is required")
        existing = application.customers.list(query=email.strip())
        customer_id = next((str(row["id"]) for row in existing if str(row["email"] or "").lower()==email.strip().lower()), None)
        if not customer_id:
            customer_id = application.customers.save({"name":name.strip(),"email":email.strip().lower(),"phone":"","notes":"Public custom-work request"})
        project = {"idea":idea,"dimensions":dimensions,"material":material,"quantity":quantity,"notes":notes}
        project["notes"] = (project["notes"] or "").strip()
        project["notes"] += ("\n" if project["notes"] else "") + "File: " + filename
        quote_id = _create_public_quote(application, customer_id, project)
        quote = application.quotes.get(quote_id)[0]
        design_id = str(uuid.uuid4())
        version_id = str(uuid.uuid4())
        safe_name = "Custom Quote " + str(quote["quote_number"])
        temp_path = None
        size = 0
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=extension) as tmp:
                temp_path = tmp.name
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_CUSTOM_UPLOAD_BYTES:
                        raise HTTPException(status_code=413, detail="3D model must be 25 MB or smaller")
                    tmp.write(chunk)
            with application.database.connect() as conn:
                conn.execute("CREATE TABLE IF NOT EXISTS quote_designs(quote_id TEXT PRIMARY KEY REFERENCES quotes(id) ON DELETE CASCADE,design_id TEXT NOT NULL UNIQUE REFERENCES designs(id) ON DELETE CASCADE,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
                conn.execute("INSERT INTO designs(id,product_id,name,current_version,notes) VALUES(?,?,?,1,?)",(design_id,None,safe_name,"Customer custom quote %s"%quote["quote_number"]))
                conn.execute("INSERT INTO design_versions(id,design_id,version,label,notes) VALUES(?,?,?,?,?)",(version_id,design_id,1,"Customer upload","Uploaded with custom quote request"))
                conn.execute("INSERT INTO quote_designs(quote_id,design_id) VALUES(?,?)",(quote_id,design_id))
                conn.commit()
            application.design_vault.import_file(design_id,temp_path,make_primary=True)
        except HTTPException:
            raise
        except Exception as exc:
            with application.database.connect() as conn:
                conn.execute("DELETE FROM quote_designs WHERE quote_id=?",(quote_id,))
                conn.execute("DELETE FROM designs WHERE id=?",(design_id,))
                conn.commit()
            raise HTTPException(status_code=500, detail="The model could not be stored") from exc
        finally:
            try:
                if temp_path: os.unlink(temp_path)
            except OSError: pass
            await file.close()
        return {"quote":_public_quote(quote),"request_number":str(quote["quote_number"]),"design_id":design_id,"file":{"name":filename,"bytes":size,"extension":extension}}

    @app.post("/api/v1/customer/quotes")
    def create_customer_quote(payload: QuoteRequest, user=Depends(current_user), application=Depends(get_application)):
        try:
            project = payload.project.dict()
            if payload.file:
                project["notes"] = (project.get("notes") or "").strip()
                project["notes"] += ("\n" if project["notes"] else "") + "File: " + str(payload.file.get("name") or "uploaded file")
            quote, items = application.customer_commerce.create_quote_request(user["id"], project)
            return {"quote": _public_quote(quote), "items": [_public_quote_item(item) for item in items]}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/customer/orders")
    def create_customer_order(payload: OrderRequest, user=Depends(current_user), application=Depends(get_application)):
        try:
            items = [item.dict() for item in payload.items]
            row, saved_items, subtotal_cents, shipping_cents, tax_cents, total_cents = application.customer_commerce.create_order(user["id"], items, payload.shippingAddress.dict(), payload.notes)
            order = _public_order(row)
            order["status"] = "Order received"
            return {"order": order, "items": [_public_order_item(item) for item in saved_items], "totals": {"subtotal": round(subtotal_cents / 100, 2), "shipping": round(shipping_cents / 100, 2), "tax": round(tax_cents / 100, 2), "total": round(total_cents / 100, 2)}}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/customer/orders/{order_id}/payment-session")
    def create_customer_payment_session(order_id: str, user=Depends(current_user), application=Depends(get_application)):
        try:
            payment = application.payments.create_checkout(user["id"], order_id)
            return {"payment": _public_payment(payment), **_public_payment(payment)}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/v1/admin/quote-requests/{quote_id}/product")
    def promote_custom_quote_to_product(quote_id: str, payload: CustomProductRequest, user=Depends(current_user), application=Depends(get_application)):
        if str(user["account_type"] or "").lower() != "administrator":
            raise HTTPException(status_code=403, detail="Administrator account required")
        try:
            result = application.custom_product_workflow.promote_quote_design(quote_id, payload.dict())
            return _json(result)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


def _create_public_quote(application, customer_id, project):
    description_parts=[project["idea"]]
    if project.get("dimensions"):description_parts.append("Dimensions: "+project["dimensions"])
    if project.get("material"):description_parts.append("Material: "+project["material"])
    if project.get("notes"):description_parts.append("Notes: "+project["notes"])
    return application.quotes.save({"customer_id":customer_id,"status":"draft","notes":project.get("notes","")},[{"product_id":None,"description":"\n".join(description_parts),"quantity":project.get("quantity",1),"unit_price_cents":0,"material":project.get("material",""),"color":"","estimated_minutes":0,"estimated_filament_g":0}])
