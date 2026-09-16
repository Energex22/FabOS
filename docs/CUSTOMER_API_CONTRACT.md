# FabOS customer API boundary

This document is the backend-side contract for the separate FabOS-Web customer frontend. The HTTP boundary is now implemented as the first FastAPI slice; create-quote/order submission and binary file upload remain later slices because they require additional business-flow decisions.

## Runtime

The API is provided by `fabos_core.api` using FastAPI and Uvicorn. The existing `FabOSApplication` and domain services remain the source of business rules and persistence.

From the FabOS repository root:

```text
python -m fabos_core.cli serve
```

The development server binds to `127.0.0.1:8000`. `FABOS_CORS_ORIGINS` may be set to a comma-separated list of allowed browser origins.

## Implemented routes

- `GET /api/v1/health`
- `GET /api/v1/catalog`
- `GET /api/v1/catalog/{product_id}`
- `GET /api/v1/catalog/categories`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/customer/me`
- `PATCH /api/v1/customer/me`
- `GET /api/v1/customer/quotes`
- `GET /api/v1/customer/quotes/{quote_id}`
- `GET /api/v1/customer/orders`
- `GET /api/v1/customer/orders/{order_id}`

## Planned routes

- `POST /api/v1/customer/quotes`
- `POST /api/v1/customer/orders`

These are deliberately not implemented with ad-hoc database writes. The next slice will extend the appropriate FabOS domain services so browser-submitted totals, product prices, customer IDs, shipping values, and ownership are resolved authoritatively inside FabOS.

## Authentication

`AuthService.login()` creates the existing server-side session token and `AuthService.authenticate()` validates it. The HTTP adapter passes the bearer token into that service rather than implementing a second password/session system.

Customer routes require an authenticated user whose account type is `customer`, and the existing customer-account linkage is used for ownership. Password hashes are never serialized into API responses.

## Domain mapping

Customer account data maps to the existing `users`, `customers`, and `customer_accounts` records. Quotes map to `quotes` and `quote_items`. Orders map to `orders` and their linked quote/items. The API uses the existing customer-scoped quote and order service methods rather than duplicating ownership queries.

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

## Request authority

Customer-submitted prices, totals, shipping charges, customer IDs, order IDs, quote IDs, permissions, and status values are untrusted input. FabOS must resolve authoritative values from its database/services and must not trust totals or ownership supplied by the browser.

The API returns HTTP errors at the boundary and intentionally uses generic ownership failures so one customer cannot use the API to enumerate another customer's records.

## File uploads

The custom-work frontend currently sends file metadata only. Binary upload/storage will be added through a dedicated authenticated file endpoint after the existing FabOS file/design-vault boundary is selected. No ad-hoc filesystem upload path is used by the customer API.
