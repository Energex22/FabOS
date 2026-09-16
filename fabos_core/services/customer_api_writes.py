"""Write-side HTTP handlers for customer commerce."""
from typing import Any, Dict, List, Optional
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

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

def register_customer_write_routes(app, get_application, current_user):
    @app.post("/api/v1/auth/register")
    def register_customer(payload: RegistrationRequest, application=Depends(get_application)):
        try:
            result = application.customer_commerce.register_customer(payload.name, payload.email, payload.password, payload.phone)
            summary = result["user"]
            return {"token": result["token"], "expires_at": result["expires_at"], "user": _json(summary["user"]), "customer": _json(summary.get("customer"))}
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
            description_parts=[project["idea"]]
            if project.get("dimensions"):description_parts.append("Dimensions: "+project["dimensions"])
            if project.get("material"):description_parts.append("Material: "+project["material"])
            if project.get("notes"):description_parts.append("Notes: "+project["notes"])
            quote_id=application.quotes.save({"customer_id":customer_id,"status":"draft","notes":project.get("notes","")},[{"product_id":None,"description":"\n".join(description_parts),"quantity":project.get("quantity",1),"unit_price_cents":0,"material":project.get("material",""),"color":"","estimated_minutes":0,"estimated_filament_g":0}])
            quote=application.quotes.get(quote_id)[0]
            return {"quote":_json(quote),"request_number":str(quote["quote_number"]),"file":payload.file}
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/customer/quotes")
    def create_customer_quote(payload: QuoteRequest, user=Depends(current_user), application=Depends(get_application)):
        try:
            project = payload.project.dict()
            if payload.file:
                project["notes"] = (project.get("notes") or "").strip()
                project["notes"] += ("\n" if project["notes"] else "") + "File: " + str(payload.file.get("name") or "uploaded file")
            quote, items = application.customer_commerce.create_quote_request(user["id"], project)
            return {"quote": _json(quote), "items": [_json(item) for item in items]}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/customer/orders")
    def create_customer_order(payload: OrderRequest, user=Depends(current_user), application=Depends(get_application)):
        try:
            items = [item.dict() for item in payload.items]
            row, saved_items, subtotal_cents, shipping_cents, tax_cents, total_cents = application.customer_commerce.create_order(user["id"], items, payload.shippingAddress.dict(), payload.notes)
            order = _json(row)
            order["status"] = "Order received"
            order.pop("customer_id", None)
            return {"order": order, "items": [_json(item) for item in saved_items], "totals": {"subtotal": round(subtotal_cents / 100, 2), "shipping": round(shipping_cents / 100, 2), "tax": round(tax_cents / 100, 2), "total": round(total_cents / 100, 2)}}
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
