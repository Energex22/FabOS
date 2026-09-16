# FabOS customer API boundary

This document is the backend-side contract for the separate FabOS-Web customer frontend. The HTTP boundary is implemented as a FastAPI + Uvicorn layer over the existing FabOS application and domain services.

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
- `POST /api/v1/customer/quotes`
- `GET /api/v1/customer/orders`
- `GET /api/v1/customer/orders/{order_id}`
- `POST /api/v1/customer/orders`

## Customer quote submission

`POST /api/v1/customer/quotes` accepts a project object containing `idea`, optional `dimensions`, `material`, `quantity`, and `notes`. A `file` object may contain metadata such as a filename; binary file transfer is intentionally not part of this endpoint.

The server resolves the authenticated customer from the session and creates the quote through FabOS's quote service. The browser cannot select another customer's ID or set an authoritative price.

## Customer order submission

`POST /api/v1/customer/orders` accepts an `items` array containing `productId`, optional `variantId`, `quantity`, and optional configuration data, plus optional order notes.

FabOS resolves the product and active variant from its catalog, calculates unit prices and the subtotal from server-side catalog data, applies the configured shipping setting, creates the linked quote/order records, and returns the authoritative totals. Browser-supplied totals, shipping amounts, customer IDs, and status values are ignored.

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

## File uploads

The custom-work frontend currently sends file metadata only. Binary upload/storage will be added through a dedicated authenticated file endpoint after the existing FabOS file/design-vault boundary is selected. No ad-hoc filesystem upload path is used by the customer API.
