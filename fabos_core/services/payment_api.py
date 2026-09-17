"""HTTP endpoints for provider callbacks and internal physical payments."""
import json

from fabos_core.services.payments import PaymentProviderError, PaymentProviderNotConfigured


def _record_refund(application, provider_name, payload):
    """Reconcile a provider refund into FabOS's existing invoice ledger.

    Refunds are stored as negative payment-ledger entries so InvoiceService.reconcile()
    computes the customer's actual net paid amount. The provider refund id (when
    available) is preferred over the webhook event id so multiple provider events for
    the same refund remain idempotent.
    """
    try:
        event = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
    except (TypeError, ValueError):
        return None

    event_id = str(event.get("id") or event.get("event_id") or "").strip()
    event_type = str(event.get("type") or "").strip().lower()
    if not event_id or "refund" not in event_type:
        return None

    obj = ((event.get("data") or {}).get("object") or {})
    metadata = {}
    if provider_name == "stripe":
        amount_cents = int(obj.get("amount") or obj.get("amount_refunded") or 0)
        provider_payment_id = str(obj.get("payment_intent") or obj.get("charge") or "")
        metadata = obj.get("metadata") or {}
        payment_id = str(metadata.get("payment_id") or "")
        refund_items = ((obj.get("refunds") or {}).get("data") or [])
        refund_id = str(refund_items[0].get("id") or "") if refund_items else ""
        if event_type == "refund.created":
            refund_id = str(obj.get("id") or refund_id)
            provider_payment_id = str(obj.get("payment_intent") or obj.get("charge") or provider_payment_id)
        refund_reference = f"stripe-refund:{refund_id or event_id}"
    elif provider_name == "square":
        refund = obj.get("refund") or obj
        amount_money = refund.get("amount_money") or {}
        amount_cents = int(amount_money.get("amount") or 0)
        provider_payment_id = str(refund.get("payment_id") or "")
        payment_id = ""
        refund_reference = f"square-refund:{refund.get('id') or event_id}"
        if str(refund.get("status") or "").upper() not in {"COMPLETED", "PENDING"}:
            return None
    else:
        return None

    if amount_cents <= 0:
        return None

    db = application.database
    with db.connect() as conn:
        existing = conn.execute("SELECT 1 FROM payments WHERE reference=? LIMIT 1", (refund_reference,)).fetchone()
        if existing:
            return {"recorded": False, "duplicate": True, "reference": refund_reference}

        transaction = None
        if payment_id:
            transaction = conn.execute("SELECT * FROM payment_transactions WHERE id=?", (payment_id,)).fetchone()
        if not transaction and provider_payment_id:
            transaction = conn.execute("SELECT * FROM payment_transactions WHERE provider_payment_id=? ORDER BY created_at DESC LIMIT 1", (provider_payment_id,)).fetchone()
        if not transaction:
            order_id = str(metadata.get("order_id") or "")
            if order_id:
                transaction = conn.execute("SELECT * FROM payment_transactions WHERE order_id=? ORDER BY created_at DESC LIMIT 1", (order_id,)).fetchone()
        if not transaction:
            return {"recorded": False, "duplicate": False, "reason": "payment_transaction_not_found"}

        invoice_id = transaction["invoice_id"]
        original_paid = int(conn.execute("SELECT COALESCE(SUM(amount_cents),0) FROM payments WHERE invoice_id=? AND amount_cents>0", (invoice_id,)).fetchone()[0] or 0)
        already_refunded = int(conn.execute("SELECT COALESCE(-SUM(amount_cents),0) FROM payments WHERE invoice_id=? AND amount_cents<0", (invoice_id,)).fetchone()[0] or 0)
        remaining = max(0, original_paid - already_refunded)
        refund_amount = min(amount_cents, remaining)
        if refund_amount <= 0:
            return {"recorded": False, "duplicate": False, "reason": "refund_exceeds_recorded_payment"}

        conn.execute(
            "INSERT INTO payments(id,invoice_id,amount_cents,method,reference,notes) VALUES(?,?,?,?,?,?)",
            (f"refund-{event_id}", invoice_id, -refund_amount, provider_name, refund_reference, "Gateway refund reconciled by FabOS"),
        )
        remaining_after = remaining - refund_amount
        new_status = "refunded" if remaining_after <= 0 else "partially_refunded"

        # Older FabOS databases predate payment_transactions.status. Refund ledger
        # reconciliation must remain safe on those databases; current schemas retain
        # the richer transaction status when the column is available.
        columns = {row[1] for row in conn.execute("PRAGMA table_info(payment_transactions)").fetchall()}
        if "status" in columns:
            conn.execute("UPDATE payment_transactions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE id=?", (new_status, transaction["id"]))
        conn.commit()

    application.invoices.reconcile(invoice_id)
    return {"recorded": True, "duplicate": False, "reference": refund_reference, "amount_cents": refund_amount, "invoice_id": invoice_id, "status": new_status}


def register_payment_routes(app, get_application, administrator_user):
    """Register HTTP payment routes without making FastAPI a test-time import requirement."""
    from fastapi import Depends, Header, HTTPException, Request
    from pydantic import BaseModel, Field

    class PhysicalPaymentRequest(BaseModel):
        order_id: str = Field(min_length=1, max_length=200)
        source_id: str = Field(min_length=1, max_length=500)
        provider: str = Field(default="square", min_length=1, max_length=30)

    @app.post("/api/v1/webhooks/payments/{provider_name}")
    async def payment_webhook(provider_name: str, request: Request, x_square_hmacsha256_signature: str = Header(default=""), stripe_signature: str = Header(default=""), application=Depends(get_application)):
        payload = await request.body()
        provider = provider_name.strip().lower()
        signature = stripe_signature if provider == "stripe" else x_square_hmacsha256_signature
        try:
            result = application.payments.handle_webhook(payload, signature, provider)
            refund = _record_refund(application, provider, payload)
            if refund:
                result["refund"] = refund
            return result
        except PaymentProviderNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PaymentProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/admin/payments/physical")
    def record_physical_payment(payload: PhysicalPaymentRequest, user=Depends(administrator_user), application=Depends(get_application)):
        try:
            return {"payment": application.payments.record_physical_payment(payload.order_id, payload.source_id, payload.provider)}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except PaymentProviderNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PaymentProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
