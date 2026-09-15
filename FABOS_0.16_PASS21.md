# FabOS 0.16 — Pass 21

## API boundary foundation

Pass 21 adds the first concrete provider-independent API transport boundary without introducing a web framework or duplicating FabOS business logic.

Added `fabos_api`:

- `FabOSAPI` handles HTTP-shaped method/path/body/header input and JSON-safe responses;
- Bearer sessions are resolved through the existing `SecurityService`;
- authentication uses the existing `AuthService`;
- customer ownership and permissions remain enforced by the existing business services;
- order status changes call the existing actor-aware `OrderService.set_status()`;
- invoice reads call the existing actor-aware invoice boundary;
- fulfillment reads call the existing actor-aware fulfillment boundary;
- a public `/api/v1/health` endpoint is provided;
- a minimal standard-library WSGI adapter is available through `create_wsgi_app()`.

## Routes

- `GET /api/v1/health`
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/me`
- `GET /api/v1/orders`
- `GET /api/v1/orders/{id}`
- `PATCH /api/v1/orders/{id}` with `{ "status": "..." }`
- `GET /api/v1/invoices`
- `GET /api/v1/invoices/{id}`
- `GET /api/v1/fulfillments`
- `GET /api/v1/fulfillments/{id}`

The API intentionally does not yet expose broad create/update operations for every domain. Those will be added behind the existing service authorization boundaries rather than allowing transport code to write directly to the database.

## Compatibility

No third-party API framework was added. This preserves the Python 3.8 baseline and keeps the desktop application architecture intact.

## Regression coverage

`tests/test_pass21_api_boundary.py` covers public health, login/session use, protected-route rejection, actor-aware order reads/mutations, invoice/fulfillment reads, and the WSGI adapter.
