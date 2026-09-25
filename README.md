# FabOS

Internal business and production system for a 3D-printing shop: products,
pricing, customers, quotes, orders, print jobs, QC, fulfillment, invoicing, and
payments. FabOS is authoritative for all of it.

FabOS also exposes a customer-facing HTTP API consumed by
[FabOS-Web](https://github.com/Energex22/FabOS-Web), the public FABVEX
storefront. Customers never need to know the internal system is called FabOS.

Current version: `0.16.0-beta.6` (`fabos_core.__version__`). Python 3.8
compatible.

## Quick start

    pip install -e .
    python -m fabos_core.cli serve      # customer HTTP API on 127.0.0.1:8000
    start_fabos.bat                     # desktop application (Windows)

Set `FABOS_DATA_DIR` to choose where the database and Design Vault live. It
defaults to `%USERPROFILE%\WireVault FabOS Data` on Windows. Always point it at
a directory outside the Git checkout.

Run the test suite with:

    python -m unittest discover -s tests -p 'test*.py' -v

## Two API entry points

There are two server processes and they are not interchangeable. Knowing which
one you are running matters, because **they read different environment
variables**.

| | `python -m fabos_core.cli serve` | `python -m fabos_api.server` |
| --- | --- | --- |
| Implementation | FastAPI + Uvicorn (`fabos_core/api.py`) | WSGI + Waitress (`fabos_api/app.py`) |
| Used by | local development, API docs | `Start-FabVex-Production.ps1` in FabOS-Web |
| Reads | `FABOS_CORS_ORIGINS`, `FABOS_ALLOWED_HOSTS`, `FABOS_API_DOCS` | `FABOS_CORS_ORIGINS` (with `FABOS_API_ALLOW_ORIGIN` as a legacy fallback), `FABOS_API_THREADS` |
| Both read | `FABOS_DATA_DIR`, `FABOS_API_HOST`, `FABOS_API_PORT`, and the payment variables | |

Both serve the same customer route set and delegate to the same FabOS services.
Neither creates a second database or a second business-logic layer.

The practical consequence: setting `FABOS_CORS_ORIGINS` or `FABOS_ALLOWED_HOSTS`
has no effect when running the Waitress server, and setting
`FABOS_API_ALLOW_ORIGIN` has no effect when running the FastAPI server. Older
deployment notes did not make this distinction.

## Customer HTTP API

Implemented customer-facing routes cover public catalog reads, customer
authentication, profile reads and updates, quote reads and submission, order
reads and submission, and payment session creation.

Customer ownership is enforced server-side and browser-submitted totals are
never authoritative. Internal production jobs, printer data, QC records,
invoices, audit records, and the internal order dossier are not exposed by the
customer API.

Custom-work file upload runs through the dedicated multipart quote-request
endpoint. STL, 3MF, OBJ, and STEP/STP files up to 25 MB are staged, validated,
imported into the Design Vault, and linked to the quote without exposing
internal filesystem paths. Payment sessions and provider webhooks are wired
through the backend payment boundary.

See [`docs/CUSTOMER_API_CONTRACT.md`](docs/CUSTOMER_API_CONTRACT.md) for the
route and data contract, and [`docs/PAYMENTS.md`](docs/PAYMENTS.md) for the
payment flow.

## Deployment

Production runs on a Windows PC with Caddy as the only public entry point:

    Browser -> Caddy (HTTPS, port 443) -> static FabOS-Web files
                                       -> /api/* -> FabOS API on 127.0.0.1:8000

Caddy serves the storefront and proxies the API on the **same hostname**, so
browser requests are same-origin and no CORS configuration is required. The
API is never directly reachable from the internet.

The Windows deployment templates, launcher scripts, and the pre-launch checklist
live in FabOS-Web at
[`deployment/windows/`](https://github.com/Energex22/FabOS-Web/tree/main/deployment/windows),
because Caddy's site root is the storefront build. Broader planning and the
go-live gate are in [`PRODUCTION_DEPLOYMENT.md`](PRODUCTION_DEPLOYMENT.md) and
[`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md).

### Domain and HTTPS setup

Caddy obtains and renews TLS certificates automatically from Let's Encrypt.
There are no certificate files to manage and no renewal task to schedule. The
work is almost entirely DNS and router configuration.

Full walkthrough:
[FabOS-Web `deployment/windows/DOMAIN_AND_HTTPS.md`](https://github.com/Energex22/FabOS-Web/blob/main/deployment/windows/DOMAIN_AND_HTTPS.md).
The short version:

1. **Check for CGNAT first.** Compare the router's WAN IP against what a "what
   is my IP" site reports. If they differ, the ISP is using carrier-grade NAT,
   inbound port forwarding cannot work, and Cloudflare Tunnel is the path
   forward. Check this before buying a domain.
2. **Register a domain** and, ideally, point its nameservers at Cloudflare DNS.
   That is optional for a basic setup but enables dynamic DNS, the DNS-01
   certificate challenge, and Cloudflare Tunnel later.
3. **Add an `A` record** for the hostname pointing at the connection's public
   IP. On Cloudflare, leave it **DNS only** (grey cloud) — the proxy prevents
   Caddy from completing its certificate challenge.
4. **Reserve a LAN address** for the server PC, then forward **TCP 80 and 443
   only**. Never forward 8000 or 5173. Allow Caddy through Windows Firewall.
5. **Copy the Caddyfile** from FabOS-Web's `deployment/windows/` to
   `C:\FabVex\Server\Caddyfile` and replace `YOUR-DOMAIN`.
6. **Start Caddy** and watch for `certificate obtained successfully`. Then test
   from a phone on cellular data, not from inside the home network — many
   routers cannot route back to their own public IP, which looks like a failure
   but is not one.
7. **Install Caddy as a Windows service** so the site survives reboots. Pass
   `--config` explicitly; services start in `System32` and will not find a
   Caddyfile beside the executable.
8. **Add dynamic DNS** if the public IP changes, using the
   `caddy-dynamicdns` app. It is not in the standard Caddy binary.

If inbound ports are blocked or unavailable, use Cloudflare Tunnel (an outbound
connection, so no port forwarding at all) or switch to the DNS-01 challenge if
only port 80 is blocked.

Once the domain is live, set the payment redirect URLs to real hostnames and
re-run the pre-launch checklist in FabOS-Web's `deployment/windows/README.md`.

## Documentation

| Document | Contents |
| --- | --- |
| [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md) | System structure |
| [`docs/CUSTOMER_API_CONTRACT.md`](docs/CUSTOMER_API_CONTRACT.md) | Customer API routes and payloads |
| [`docs/PAYMENTS.md`](docs/PAYMENTS.md) | Payment boundary and webhooks |
| [`docs/PRODUCTION_READINESS.md`](docs/PRODUCTION_READINESS.md) | Acceptance, recovery, and security checks |
| [`PRODUCTION_DEPLOYMENT.md`](PRODUCTION_DEPLOYMENT.md) | Deployment plan and go-live gate |
| [`docs/security/SECURITY.md`](docs/security/SECURITY.md) | Security model |
| [`docs/testing/TEST_PLAN.md`](docs/testing/TEST_PLAN.md) | Test strategy |
| [`docs/PLUGIN_SDK.md`](docs/PLUGIN_SDK.md) | Plugin interface |
| [`docs/MARKETING_HUB.md`](docs/MARKETING_HUB.md) | Marketing channels, campaigns, posts, marketplace sales, and owner setup |
| [`docs/AI_ASSISTANT.md`](docs/AI_ASSISTANT.md) | AI provider setup, safety defaults, and marketing assistance |
| [`docs/ROADMAP.md`](docs/ROADMAP.md) | Planned work |
| [`deployment/windows/README.md`](deployment/windows/README.md) | Backups and host hardening |

Per-release history is in the `RELEASE_NOTES_*.md`, `BUILD_STATUS_*.md`,
`HOTFIX_*.md`, and `FABOS_0.16_PASS*.md` files at the repository root.

## Operating rules

- FabOS is authoritative for product eligibility, variants, pricing, tax,
  shipping, order totals, and payment state. The browser cart is display state.
- Keep the database and Design Vault on persistent storage. The SQLite and
  Design Vault architecture must not run on an ephemeral filesystem.
- Payment secrets, printer API keys, database files, and customer uploads never
  go into Git.
- Do not publish FabOS desktop or administrative surfaces through Caddy.
- Do not run a development server as the public production server.
- CI passing proves source and build integrity only. It does not prove payment
  credentials, printer connectivity, filesystem permissions, DNS, TLS, or
  working backups.
