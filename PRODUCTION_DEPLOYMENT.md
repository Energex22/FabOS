# FabOS Production Deployment Plan

This is the production path for FabOS + FabOS-Web. FabOS remains authoritative for products, pricing, orders, customers, fulfillment, and payment state.

## Recommended architecture

Customer browser -> FabOS-Web static frontend -> HTTPS -> FabOS customer API -> FabOS services + persistent database/Design Vault.

Stripe Checkout is the payment boundary. FabOS never stores raw card data.

For the first public beta, keep FabOS on a dedicated Windows PC/server and expose only the HTTPS API through a managed tunnel. Do not forward ports 8000/5173 directly from the router.

## Public hosting

FabOS-Web can be deployed as a static site on GitHub Pages, Cloudflare Pages, or Render Static Sites.

The FabOS API should remain on infrastructure with persistent storage. The current SQLite/Design Vault architecture must not be placed on an ephemeral filesystem.

## Production API environment

Required values:

- FABOS_API_HOST=127.0.0.1
- FABOS_API_PORT=8000
- FABOS_API_DOCS=false
- FABOS_CORS_ORIGINS=https://YOUR-DOMAIN
- FABOS_PAYMENT_PROVIDER=stripe
- STRIPE_SECRET_KEY=<secret>
- STRIPE_WEBHOOK_SECRET=<secret>
- STRIPE_SUCCESS_URL=https://YOUR-DOMAIN/checkout.html?payment=success
- STRIPE_CANCEL_URL=https://YOUR-DOMAIN/checkout.html?payment=cancelled

Never commit real credentials.

## FabOS-Web environment

Set VITE_API_URL to the public HTTPS API before building:

VITE_API_URL=https://api.YOUR-DOMAIN

Anything prefixed with VITE_ is delivered to the browser. Never place Stripe secret keys there.

## Domain

A permanent free custom domain should not be assumed. Hosting-generated subdomains are useful for testing, but the production storefront should use a domain controlled by the business.

Do not purchase a domain until the desired FabVex domain has been checked for availability and trademark/business-name conflicts.

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

- [ ] HTTPS API reachable.
- [ ] CORS restricted to the storefront.
- [ ] Public API docs disabled.
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

The second-PC/server approach is therefore the zero-monthly-hosting path that best matches the current FabOS architecture. The machine should not be directly exposed to the internet; the tunnel is the public boundary.
