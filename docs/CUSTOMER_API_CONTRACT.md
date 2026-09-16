# FabOS customer API boundary

This document is the backend-side contract for the separate FabOS-Web customer frontend. FabOS remains the business-rule and persistence layer; customers never need to know that FabOS exists.

## Runtime

The API is provided by `fabos_core.api` using FastAPI and Uvicorn. The existing `FabOSApplication` and domain services remain the source of business rules and persistence.

From the FabOS repository root:

```text
python -m fabos_core.cli serve
```

The development server binds to `127.0.0.1:8000`. `FABOS_CORS_ORIGINS` may be set to a comma-separated list of allowed browser origins.

## Public customer routes

- `GET /api/v1/health`
- `GET /api/v1/catalog`
- `GET /api/v1/catalog/{product_id}`
- `GET /api/v1/catalog/categories`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `POST /api/v1/auth/register`
- `GET /api/v1/customer/me`
- `PATCH /api/v1/customer/me`
- `GET /api/v1/customer/quotes`
- `GET /api/v1/customer/quotes/{quote_id}`
- `POST /api/v1/customer/quotes`
- `POST /api/v1/quote-requests`
- `POST /api/v1/quote-requests/upload`
- `GET /api/v1/customer/orders`
- `GET /api/v1/customer/orders/{order_id}`
- `POST /api/v1/customer/orders`
- `POST /api/v1/customer/orders/{order_id}/payment-session`

Payment-provider webhooks and physical-sale payment ingestion are internal integration routes and are not customer-facing.

## Catalog eligibility

The public catalog is generated from FabOS's catalog source of truth. A product is exposed to customers only when its storefront visibility is `published`, it has a usable printable model, it has a positive customer price, and its license status is commercially acceptable.

The customer API deliberately strips internal production files, license metadata, source URLs, and designer/internal provenance fields from the public product representation.

## Public custom quote requests

`POST /api/v1/quote-requests` accepts customer/project information for a custom-work request without requiring an account.

`POST /api/v1/quote-requests/upload` accepts the same project fields as multipart form data plus a real model/reference file. Approved model formats include STL, 3MF, OBJ, STEP/STP, with a 25 MB upload limit. The upload is imported into Design Vault and linked to the quote; temporary upload files are removed and internal filesystem paths are never returned to the customer.

A public custom request may later be promoted internally into a catalog product. When that happens, the product retains its customer-custom origin and source-customer linkage while still using the same storefront publication rules as other products.

## Customer quote submission

`POST /api/v1/customer/quotes` accepts a project object containing `idea`, optional `dimensions`, `material`, `quantity`, and `notes`. The server resolves the authenticated customer from the session and creates the quote through FabOS's quote service. The browser cannot select another customer's ID or set an authoritative price.

## Customer order submission

`POST /api/v1/customer/orders` accepts an `items` array containing `productId`, optional `variantId`, `quantity`, and optional configuration data, plus a required `shippingAddress` and optional order notes.

FabOS resolves the product and active variant from its catalog. A product must satisfy customer catalog eligibility before it can be ordered. Unit prices, subtotal, tax, shipping, and total are calculated from server-side catalog/shop settings. The browser cannot set authoritative totals, customer IDs, payment state, or order status.

The order stores the shipping address in the existing `orders.shipping_address_json` field and records the checkout channel as `website`.

## Online payment

`POST /api/v1/customer/orders/{order_id}/payment-session` initializes the provider-neutral FabOS payment layer for an authenticated customer's own order.

For online checkout, Stripe is the primary processor. FabOS creates the provider session without receiving or storing raw card data. When Stripe is not configured, the order remains safely recorded and the customer receives a setup/pending response rather than a fake payment-success state.

Stripe webhook callbacks update the FabOS payment transaction and invoice ledger. Refunds are represented as negative ledger entries and are idempotent, preventing duplicate webhook deliveries from double-counting a refund.

Square is reserved for physical/in-person sales. Both providers ultimately reconcile into the same FabOS order, invoice, and production workflow.

## Authentication

`AuthService.login()` creates the existing server-side session token and `AuthService.authenticate()` validates it. The HTTP adapter passes the bearer token into that service rather than implementing a second password/session system.

Customer routes require an authenticated user whose account type is `customer`, and the existing customer-account linkage is used for ownership. Password hashes are never serialized into API responses.

## Domain mapping

Customer account data maps to the existing `users`, `customers`, and `customer_accounts` records. Quotes map to `quotes` and `quote_items`. Orders map to `orders` and their linked quote/items. Checkout shipping/tax/channel fields use the existing order migration fields. The API uses existing customer-scoped quote and order service methods rather than duplicating ownership queries.

The internal order `dossier()` is never exposed through this boundary because it contains production jobs, QC, invoices, payments, fulfillment, and other operational information.

## Customer-safe order statuses

The API translates internal statuses into stable customer-facing labels:

- `new`, `pending`, `confirmed` → `Order received`
- `in_production` → `Preparing your order`
- `ready` → `Final quality check`
- `shipped` → `Shipping`
- `completed` → `Delivered`
- `cancelled` → `Cancelled`

The translation belongs in the API serializer so internal workflow changes do not become frontend breaking changes.

## Security boundary

Customers never receive Design Vault paths, internal production records, raw payment credentials, payment-provider secrets, or another customer's identifiers. Server-side ownership and eligibility checks are repeated at order/payment boundaries rather than trusting frontend state.
