# FabOS Production Deployment Plan

This is the production path for FabOS + FabOS-Web. FabOS remains authoritative for products, pricing, orders, customers, fulfillment, and payment state.

## Recommended architecture

Same-origin deployment behind Caddy on a dedicated Windows PC:

    Browser -> Caddy (HTTPS, 443) -> static FabOS-Web build
                                  -> /api/* -> FabOS API on 127.0.0.1:8000
                                            -> FabOS services + persistent
                                               database and Design Vault

Caddy serves the storefront and proxies the API under one hostname, so browser
requests are same-origin. This means no CORS configuration is required and the
API is never directly reachable from the internet.

Stripe Checkout is the payment boundary. FabOS never stores raw card data.

The public boundary is either router port forwarding of TCP 80 and 443 to
Caddy, or an outbound tunnel such as Cloudflare Tunnel where inbound ports are
blocked or the connection is behind CGNAT. Either way, never forward ports 8000
or 5173. See the domain and HTTPS guide in FabOS-Web at
`deployment/windows/DOMAIN_AND_HTTPS.md`.

## Alternative: split-origin hosting

FabOS-Web can instead be deployed as a static site on GitHub Pages, Cloudflare
Pages, or Render Static Sites, with the API on a separate public hostname.

This is **not the current approach.** It requires building the frontend with an
absolute `VITE_API_URL`, exposing the API publicly under its own hostname, and
maintaining a correct `FABOS_CORS_ORIGINS` allowlist — strictly more attack
surface than the same-origin design for no benefit at this scale. The GitHub
Pages workflow in FabOS-Web is disabled for this reason and documents how to
re-enable it.

The FabOS API must remain on infrastructure with persistent storage under either
approach. The current SQLite and Design Vault architecture must not be placed on
an ephemeral filesystem.

## Backend install (Windows PC)

Prerequisites: Git, **Python 3.11 or newer** (3.12 recommended), Node.js LTS,
and Caddy for Windows.

1. Clone FabOS and FabOS-Web to their target directories
   (`C:\FabVex\FabOS`, `C:\FabVex\FabOS-Web`).
2. Create the backend virtual environment and install dependencies:

       cd C:\FabVex\FabOS
       py -3 -m venv .venv
       .\.venv\Scripts\python.exe -m pip install --upgrade pip
       .\.venv\Scripts\python.exe -m pip install .

   (`Setup-FabVex.ps1` in FabOS-Web does this automatically along with the
   frontend build.)
3. Copy `server.env.example` to a private `server.env` and set at least
   `FABOS_DATA_DIR` to a directory **outside** any Git checkout
   (e.g. `C:\FabVex\Data`).
4. Database setup is automatic: the first API start creates the SQLite
   database at `FABOS_DATA_DIR`, applies `schema.sql`, and runs migrations
   1–60 in order. No manual migration step is needed; upgrades re-run only
   pending migrations.

Start the API (FastAPI + Uvicorn — the primary production path):

    cd C:\FabVex\FabOS
    .\.venv\Scripts\python.exe deployment\windows\run_api_service.py --env-file deployment\windows\server.env

Or use `Start-FabVex-Production.ps1` (FabOS-Web) for the full stack
(API + storefront + Caddy) with preflight checks.

## First-run checklist (in order)

1. Start the API once and confirm `http://127.0.0.1:8000/api/v1/health` responds.
   This creates and migrates the database.
2. Create the owner/admin account: `python -m fabos_core.cli setup-owner`
   (or option 7 in `start_fabos.bat`). Change the bootstrap password immediately.
3. In the admin console, open **Settings > Integrations** and enter the
   Resend API key (customer notification emails stay logged-only until set).
4. In **Settings**, review business details: shop name, contact, tax state,
   quote validity period (default 14 days).
5. Add Stripe test-mode keys (Settings > Integrations or `server.env`) and
   configure the webhook; run a complete test order before live credentials.
6. Create and verify the first backup:
   `python -m fabos_core.cli backup` then `backup-check`.
7. Run `python -m fabos_core.cli production-check` and resolve anything it flags.
8. Only then put the site on a public domain (see the Windows deployment
   README's bring-up steps and DOMAIN_AND_HTTPS.md).

## Production API environment

Required for every deployment:

- FABOS_DATA_DIR=<persistent directory outside the Git checkout>
- FABOS_API_HOST=127.0.0.1
- FABOS_API_PORT=8000
- FABOS_PAYMENT_PROVIDER=stripe
- STRIPE_SECRET_KEY=<secret>
- STRIPE_WEBHOOK_SECRET=<secret>
- STRIPE_SUCCESS_URL=https://YOUR-DOMAIN/orders.html
- STRIPE_CANCEL_URL=https://YOUR-DOMAIN/checkout.html

Secrets (Stripe keys, Resend key, Square keys) can be entered in the admin
console under Settings > Integrations instead of environment variables — that
is the preferred place: values are masked, writes are admin-gated, and no
restart is needed. Environment variables below are a fallback used only when
the corresponding setting is empty. Never commit real credentials anywhere.

Optional, for customer transactional-notification email (Phase 2):

- RESEND_API_KEY=<secret> — or set `resend_api_key` in Settings > Integrations
  (preferred). When unset everywhere, notification emails are logged instead
  of sent (dev-safe) and the in-app notification center still works.
- RESEND_FROM_EMAIL="FABVEX <hello@fabvex.com>" — or the `resend_from_email`
  setting; falls back to the `notification_from_email` shop setting, then
  `shop_email`.

Optional, for in-person payments via Square (Phase 3):

- SQUARE_ACCESS_TOKEN=<secret> (or `square_access_token` setting)
- SQUARE_LOCATION_ID=<id> (or `square_location_id` setting)
- SQUARE_WEBHOOK_SIGNATURE_KEY=<secret> (or setting)
- SQUARE_WEBHOOK_URL=<url> (or setting)

Optional shop setting (Settings > Notifications in the admin console):

- `public_base_url` — e.g. `https://shop.fabvex.com`. Notification emails use
  absolute deep links when set; otherwise links are relative paths.

The two server entry points read different hardening variables. See the table
in `README.md` under "Two API entry points".

- Running `python -m fabos_api.server` (what `Start-FabVex-Production.ps1`
  uses): `FABOS_API_ALLOW_ORIGIN`, `FABOS_API_THREADS`. `FABOS_CORS_ORIGINS`,
  `FABOS_ALLOWED_HOSTS`, and `FABOS_API_DOCS` are ignored on this path.
- Running `python -m fabos_core.cli serve`: `FABOS_API_DOCS=false`,
  `FABOS_ALLOWED_HOSTS=YOUR-DOMAIN`, and — only for split-origin hosting —
  `FABOS_CORS_ORIGINS=https://YOUR-DOMAIN`.

The redirect URLs above must point at pages that work without query parameters.
Note that the storefront currently has **no post-redirect payment handler**: it
does not read a `?payment=success` parameter, and `/order.html` needs an `?id=`
that Stripe will not supply. `/orders.html` loads from the customer account and
is therefore the correct landing page until a dedicated handler exists.

Never commit real credentials.

## FabOS-Web environment

For the same-origin Caddy deployment, leave the API base relative:

    VITE_API_URL=/api

The browser then calls `/api` on whatever hostname served the page, and Caddy
forwards it to the local API. Only set an absolute URL if deliberately using the
split-origin approach above.

Anything prefixed with VITE_ is delivered to the browser. Never place Stripe
secret keys there.

## Domain

A permanent free custom domain should not be assumed. Hosting-generated subdomains are useful for testing, but the production storefront should use a domain controlled by the business.

Do not purchase a domain until the desired FabVex domain has been checked for availability and trademark/business-name conflicts.

Check for CGNAT before buying anything: if the router's WAN IP does not match the connection's visible public IP, inbound port forwarding cannot work and the deployment needs an outbound tunnel instead. Step-by-step registration, DNS, port forwarding, certificate issuance, Windows service installation, and tunnel fallbacks are documented in FabOS-Web at `deployment/windows/DOMAIN_AND_HTTPS.md`.

## Production data

The server needs:

1. Persistent FabOS data directory.
2. Automated backups.
3. Backup verification.
4. Restricted filesystem permissions.
5. A tested recovery procedure.

## Stripe activation

Before live mode:

1. Create the Stripe account.
2. Complete Stripe business verification.
3. Create test-mode credentials.
4. Configure the webhook.
5. Run a complete test order.
6. Confirm the webhook records payment and confirms the order.
7. Confirm duplicate webhook delivery is idempotent.
8. Test failed payment.
9. Test refund.
10. Only then switch to live credentials.

## Go-live gate

- [ ] HTTPS reachable from outside the local network.
- [ ] TLS certificate issued and auto-renewal confirmed.
- [ ] API not directly reachable on port 8000 from the internet.
- [ ] CORS restricted to the storefront, if using split-origin hosting.
- [ ] Public API docs disabled, if running the FastAPI server.
- [ ] No secrets in Git.
- [ ] Catalog comes from FabOS.
- [ ] Server-side pricing is authoritative.
- [ ] Shipping is authoritative.
- [ ] Tax is authoritative.
- [ ] Customer ownership checks pass.
- [ ] Custom 3D-file upload works with size/type limits.
- [ ] Stripe test checkout works.
- [ ] Stripe webhook signature verification works.
- [ ] Payment idempotency works.
- [ ] Order states are correct.
- [ ] Backups restore successfully.
- [ ] Known physical print passes through the FabOS workflow.
- [ ] Clean-browser checkout succeeds.
- [ ] Failed checkout cannot create a false paid state.
- [ ] Refunds reconcile correctly.
- [ ] Shipping/tax rules have been reviewed for every jurisdiction where FabVex will sell.

## Free-hosting caution

Render currently offers free web services, but its free web-service filesystem is ephemeral and its free Postgres database expires after 30 days. That makes it unsuitable for the current persistent SQLite/Design Vault production architecture. It is useful for disposable testing.

The second-PC/server approach is therefore the zero-monthly-hosting path that best matches the current FabOS architecture. Only Caddy is exposed; the FabOS API stays bound to 127.0.0.1 behind it.
