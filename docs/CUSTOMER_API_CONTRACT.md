# FabOS customer API boundary

This document is the backend-side contract for the separate FabOS-Web customer frontend. The routes below are the intended HTTP boundary; they are not implemented by this document alone.

## Existing domain services

FabOS already contains dedicated services for accounts/authentication, customers, quotes, orders, products, fulfillment, and customer updates. The application wires these services together as separate boundaries rather than putting customer behavior into the frontend. The customer HTTP layer should call these services and enforce the existing ownership/RBAC rules.

## Routes

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

## Authentication

`AuthService.login()` already creates a server-side session token and `AuthService.authenticate()` validates it. The HTTP adapter must pass the bearer token into this service rather than implementing a second password/session system.

Customer routes must require an authenticated user with `account_type == "customer"` and must use the existing customer-account linkage. Customer ownership checks must happen server-side.

## Domain mapping

Customer account data maps to the existing `users`, `customers`, and `customer_accounts` records. Quotes map to `quotes` and `quote_items`. Orders map to `orders` and their linked quote/items. Customer-safe fulfillment information may be returned from the fulfillment record, but operational printer, production-job, staff, audit, and internal-note data must remain private.

The existing order service already provides `get_for_user()` and `list_for_user()` ownership boundaries. The HTTP layer should use those methods instead of duplicating ownership queries.

## Customer-safe order statuses

Internal order statuses currently include `pending`, `confirmed`, `in_production`, `ready`, `shipped`, `completed`, and `cancelled`. The customer API should translate those into stable UI states:

1. Order received
2. Payment
3. Preparing your order
4. Final quality check
5. Shipping
6. Delivered

The translation belongs in the API serializer so internal workflow changes do not become frontend breaking changes.

## Request authority

Customer-submitted prices, totals, shipping charges, customer IDs, order IDs, quote IDs, permissions, and status values are untrusted input. FabOS must resolve authoritative values from its database/services and must not trust totals or ownership supplied by the browser.

The API should return structured errors with appropriate HTTP status codes. In particular, ownership failures must not disclose whether another customer's record exists.

## File uploads

The custom-work frontend currently sends file metadata only. Binary upload/storage should be added through a dedicated authenticated file endpoint after the existing FabOS file/design-vault boundary is selected. Do not add an ad-hoc filesystem upload path to the customer API.
