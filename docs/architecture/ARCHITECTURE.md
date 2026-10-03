# FabOS Architecture

FabOS is the authoritative business and manufacturing engine behind FABVEX.

## System boundary

```text
Customer / Staff Browser
        |
        v
   FabOS-Web
   presentation
        |
   HTTPS / JSON
        |
        v
      FabOS
  business services
        |
   +----+-------------------+
   |                        |
 SQLite + Design Vault   Integrations
   |                        |
   |                 +------+-------+
   |                 |              |
   |              Stripe       OctoPrint
   |                 |
   |            AI / providers
   |
   +--> production jobs / QC / fulfillment
```

FabOS-Web is a presentation/client layer. It must not become a second source of truth for pricing, ownership, payment state, production state, or fulfillment.

## Core principles

- **Server authority:** money, permissions, ownership, catalog eligibility, order totals, payment state, production state, and fulfillment state are validated in FabOS.
- **Persistent state:** SQLite and the Design Vault live outside the Git checkout and are backed up independently.
- **Versioned designs:** customer/design files are associated with immutable/versioned records rather than being silently overwritten.
- **Transactional commands:** business state transitions should be atomic and recoverable.
- **Durable boundaries:** external callbacks and automation are designed to be repeatable/idempotent where the operation can be delivered more than once.
- **Integration isolation:** plugins/providers use FabOS service/event boundaries rather than arbitrary direct database access.
- **Customer-safe API:** internal production, printer, staff, audit, credential, and filesystem information is not exposed to customer accounts.
- **Production gating:** custom production can be blocked by required customer proof/approval state.

## Customer custom-work lifecycle

```text
Request
  -> Quote
  -> Design
  -> Design Version
  -> Proof
  -> Customer Approval
  -> Order
  -> Production Job
  -> Print
  -> QC / Rework
  -> Fulfillment
```

The proof gate is server-enforced for workflows that require customer approval.

## Deployment boundary

The supported public architecture is:

```text
Internet
   |
 HTTPS 443
   |
 Caddy
   +--> FabOS-Web static build
   |
   +--> /api/* -> FabOS FastAPI/Uvicorn
                    |
                 127.0.0.1:8000
```

The Windows production launcher uses the FastAPI/Uvicorn service behind Caddy. The Waitress entry point remains available as an alternative/legacy server path and should not be confused with the canonical storefront deployment.

Do not expose ports 8000 or 5173 directly to the internet.

## Integration boundaries

### Payments
Stripe is the primary online payment boundary. FabOS records payment state and reconciles provider webhooks; raw card data is not stored by FabOS.

### Printers
OctoPrint is an optional remote-control integration. Printer access is explicitly configured per deployment.

### AI
AI providers are optional. The assistant is advisory by default and consequential operations remain behind explicit FabOS workflows.

### Marketing
Marketing and marketplace providers are normalized behind provider-specific integration seams. Provider adapters are not assumed to be universally automated.

## Runtime data

The repository contains source code and deployment helpers. Persistent runtime data should remain outside the checkout:

- SQLite database;
- Design Vault/customer uploads;
- backup archives;
- provider secrets;
- printer credentials;
- AI credentials;
- production environment files.

## Recovery model

A production deployment is not considered ready merely because the application starts.

The acceptance gate includes:

1. schema migration;
2. owner setup;
3. backup creation;
4. backup verification;
5. restore testing;
6. customer checkout;
7. payment webhook idempotency;
8. customer proof approval where required;
9. print/QC/fulfillment flow;
10. restart/recovery testing.

See [docs/PRODUCTION_READINESS.md](../PRODUCTION_READINESS.md) and [PRODUCTION_DEPLOYMENT.md](../../PRODUCTION_DEPLOYMENT.md).
