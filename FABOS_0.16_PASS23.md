# FabOS 0.16 — Pass 23

## Local API integration foundation

Pass 23 adds a dependency-free local development server around the existing FabOS API boundary.

### Added

- `fabos_api/server.py`
- Local WSGI server using Python's standard library.
- Default address: `http://127.0.0.1:8000`.
- Health endpoint: `/api/v1/health`.
- Browser CORS support for the separate frontend, defaulting to `http://localhost:5173`.
- OPTIONS preflight handling.
- Configurable with `FABOS_API_HOST`, `FABOS_API_PORT`, and `FABOS_API_ALLOW_ORIGIN`.
- Regression tests for health responses and CORS preflight.

The server creates the existing `FabOSApplication`; it does not create a second database, business-logic layer, or alternate production workflow.

## Website testing path

The separate customer website can now run against the local FabOS API once the frontend is connected to `http://127.0.0.1:8000`.

The intended local setup is:

1. Start the FabOS API development server on port 8000.
2. Start the separate customer frontend on port 5173.
3. The frontend calls `/api/v1/...` through the API base URL.
4. Authentication uses the existing FabOS bearer-session service.
5. Product/customer/quote/order/invoice/fulfillment rules continue to execute inside FabOS.

This pass does not move the customer website into the FabOS repository and does not replace the existing desktop application.
