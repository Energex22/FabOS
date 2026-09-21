# FABVEX / FabOS production readiness

This document is the deployment checklist for the current FabOS + FABVEX storefront architecture.

## Architecture

- FabOS is the internal business/production system and API.
- FabOS-Web is the public FABVEX storefront.
- Customers never need to know that the internal system is called FabOS.
- The browser cart is convenience state; FabOS is authoritative for product eligibility, variants, pricing, tax, shipping, order totals, and payment state.

## Required backend environment

Set these before exposing the customer API publicly:

- FABOS_DATA_DIR — persistent writable application-data directory.
- FABOS_CORS_ORIGINS — comma-separated production storefront origins only. Do not leave localhost defaults in production.
- FABOS_API_DOCS — leave unset/false in production unless API documentation is intentionally public.
- Configure the selected payment provider credentials/secrets using the provider settings already supported by FabOS.
- Configure the payment webhook endpoint/signature secret in the payment provider and FabOS settings.
- Configure OctoPrint URLs/API keys only for printers that should be remotely controlled.
- Configure backup storage with enough capacity for the database and uploaded customer designs.

## First-run checklist

1. Start FabOS once against the intended persistent data directory.
2. Confirm migrations reach the current schema version.
3. Create the initial owner/administrator explicitly; do not rely on database role defaults.
4. Change the initial owner password before production use.
5. Confirm the storefront contains only products intentionally marked customer-eligible/published.
6. Confirm every published product has a valid customer price and printable model.
7. Configure tax/shipping/pricing settings.
8. Configure the payment provider and webhook secret.
9. Configure the production printer(s), Cura profile, filament inventory, and spool data.
10. Run a backup and verify that the backup can be opened/restored before taking real orders.

## Customer acceptance test

Run this once against the production-like environment:

1. Register a new customer account.
2. Log in and refresh the session.
3. Browse the published catalog and a product with variants.
4. Add two different products and two variants of the same product to the cart.
5. Change quantities and confirm the cart remains bounded and correctly separated by variant.
6. Complete checkout with a test address.
7. Confirm the server recalculates totals rather than trusting browser totals.
8. Start payment and complete a test payment.
9. Deliver the provider webhook twice and confirm the second delivery is idempotent.
10. Open the order from the customer account and confirm only that customer's data is visible.
11. Create a custom-work request with a supported model file.
12. Confirm the quote, design, design version, and uploaded file are linked.
13. Review/price the custom quote as an administrator and promote it to a product.
14. Repeat the promotion and confirm it reuses the existing product/design relationship instead of creating a duplicate.
15. Confirm the resulting order creates one production job per requested quantity/variant.
16. Print a test job, record filament consumption, complete QC, and verify rework/reprint behavior.
17. Set fulfillment to shipping or pickup and complete it.
18. Confirm invoice/payment reconciliation and final customer-facing order status.

## Recovery test

Before live use, intentionally test:

- restart during an active print;
- restore the latest database backup into a separate test directory;
- reopen the restored database and verify orders, designs, invoices, inventory, and print jobs;
- re-run a previously delivered payment webhook;
- retry a failed payment;
- retry a failed/reprinted production job.

## Security checks

- Production CORS contains only trusted storefront origins.
- API documentation is not publicly exposed unless deliberately enabled.
- Customer endpoints always scope records to the authenticated customer.
- Internal dossier/admin endpoints are not exposed to customer accounts.
- Diagnostic/log exports redact credentials, bearer tokens, cookies, and secrets.
- Customer-upload paths are kept behind the design/file service and never returned as internal filesystem paths.
- Backups are stored outside the public web root.
- Payment secrets and printer API keys are never committed to Git.

## Hardware readiness

For the current Anycubic Vyper/Cura workflow:

- verify the installed Cura profile;
- verify nozzle/bed/material presets;
- run a small known-good calibration print;
- verify OctoPrint connection only after local printing is confirmed;
- keep the printer in simulation/manual mode until the first automated job is observed end-to-end.

## Release rule

Do not merge to main or expose the storefront publicly until the acceptance and recovery checks above have been run in the actual deployment environment. CI passing proves source/build integrity; it does not prove payment credentials, printer connectivity, filesystem permissions, DNS, TLS, or production backups.
