"""HTTP endpoints for provider callbacks and internal physical payments."""
from fastapi import Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from fabos_core.services.payments import PaymentProviderError, PaymentProviderNotConfigured


class PhysicalPaymentRequest(BaseModel):
    order_id: str = Field(min_length=1, max_length=200)
    source_id: str = Field(min_length=1, max_length=500)
    provider: str = Field(default="square", min_length=1, max_length=30)


def register_payment_routes(app, get_application, administrator_user):
    @app.post("/api/v1/webhooks/payments/{provider_name}")
    async def payment_webhook(
        provider_name: str,
        request: Request,
        x_square_hmacsha256_signature: str = Header(default=""),
        stripe_signature: str = Header(default=""),
        application=Depends(get_application),
    ):
        payload = await request.body()
        provider = provider_name.strip().lower()
        signature = stripe_signature if provider == "stripe" else x_square_hmacsha256_signature
        try:
            return application.payments.handle_webhook(payload, signature, provider)
        except PaymentProviderNotConfigured as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except PaymentProviderError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/v1/admin/payments/physical")
    def record_physical_payment(
        payload: PhysicalPaymentRequest,
        user=Depends(administrator_user),
        application=Depends(get_application),
    ):
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
