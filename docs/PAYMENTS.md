# FabOS Payments

FabOS uses a provider-neutral payment layer. The customer storefront does not choose a gateway.

## Online sales — Stripe

Set these environment variables on the FabOS API process:

```text
FABOS_PAYMENT_PROVIDER=stripe
STRIPE_SECRET_KEY=sk_test_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_SUCCESS_URL=https://your-store.example/checkout.html?payment=success
STRIPE_CANCEL_URL=https://your-store.example/checkout.html?payment=cancelled
```

The customer API creates a Stripe Checkout Session at:

`POST /api/v1/customer/orders/{order_id}/payment-session`

Stripe should send webhook events to:

`POST /api/v1/webhooks/payments/stripe`

At minimum, configure the webhook endpoint for successful and failed payment events. FabOS verifies the Stripe `Stripe-Signature` header, stores webhook event IDs for idempotency, records the payment against the FabOS invoice, and moves a pending order to `confirmed` after a successful payment.

FabOS never receives or stores raw card numbers.

## Physical sales — Square

Set:

```text
SQUARE_ACCESS_TOKEN=EAAA...
SQUARE_LOCATION_ID=...
SQUARE_WEBHOOK_SIGNATURE_KEY=...
SQUARE_WEBHOOK_URL=https://your-api.example/api/v1/webhooks/payments/square
```

A trusted internal caller can record a physical Square payment with:

`POST /api/v1/admin/payments/physical`

using:

```json
{
  "order_id": "...",
  "source_id": "...",
  "provider": "square"
}
```

The `source_id` is a Square payment source/token produced by the Square client or terminal flow. FabOS does not store card data.

Square webhooks should target:

`POST /api/v1/webhooks/payments/square`

FabOS verifies the Square HMAC signature, deduplicates webhook event IDs, reconciles the payment to the invoice, and confirms the order after payment.

## Current safety behavior

If payment credentials are absent, customer orders can still be recorded but the payment session returns `not_configured`; FabOS does not pretend that money was collected.

Provider credentials should be supplied through the process environment or the deployment's secret store. Do not commit live credentials to the repository.
