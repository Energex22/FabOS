"""Write-side HTTP handlers for customer commerce."""
from typing import Any
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

class QuoteProject(BaseModel):
    idea: str = Field(min_length=1, max_length=4000)
    dimensions: str = Field(default="", max_length=1000)
    material: str = Field(default="", max_length=200)
    quantity: int = Field(default=1, ge=1, le=1000)
    notes: str = Field(default="", max_length=4000)

class QuoteRequest(BaseModel):
    project: QuoteProject
    file: dict[str, Any] | None = None

class OrderItem(BaseModel):
    productId: str = Field(min_length=1, max_length=200)
    variantId: str | None = Field(default=None, max_length=200)
    quantity: int = Field(default=1, ge=1, le=1000)
    configuration: dict[str, Any] | None = None

class OrderRequest(BaseModel):
    items: list[OrderItem] = Field(min_length=1, max_length=100)
    notes: str = Field(default="", max_length=4000)

def register_customer_write_routes(app, get_application, current_user):
    @app.post("/api/v1/customer/quotes")
    def create_customer_quote(payload: QuoteRequest, user=Depends(current_user), application=Depends(get_application)):
        try:
            project = payload.project.model_dump()
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
            items = [item.model_dump() for item in payload.items]
            row, saved_items, subtotal_cents, shipping_cents, total_cents = application.customer_commerce.create_order(user["id"], items, payload.notes)
            order = _json(row)
            order["status"] = "Order received"
            order.pop("customer_id", None)
            return {"order": order, "items": [_json(item) for item in saved_items], "totals": {"subtotal": round(subtotal_cents / 100, 2), "shipping": round(shipping_cents / 100, 2), "total": round(total_cents / 100, 2)}}
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
