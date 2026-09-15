# FabOS 0.16 — Pass 18

## Payment and invoice authorization boundary

Pass 18 hardens the existing invoice/payment implementation without creating a second payment system.

### Implemented

- Extended `InvoiceService` with provider-independent authorization dependencies for `AccountService` and `PermissionService`.
- Added actor-aware invoice reads with `payment.read` enforcement.
- Customer invoice access is isolated to invoices belonging to orders for the customer's linked customer record.
- Added actor-aware invoice creation, charge updates, payment recording, and void operations requiring `payment.manage`.
- Customer accounts cannot create, modify, record payments on, or void invoices.
- Employee and administrator access continues through the existing RBAC layer.
- User-specific permission overrides remain enforced.
- Added customer-safe payment history filtering.
- Existing internal invoice methods remain available to preserve the current desktop/business workflow; customer-facing/API code should use the actor-aware boundary methods.
- Application wiring now passes the existing account and permission services into `InvoiceService`.

### Test hardening

Added a GitHub Actions test workflow covering Python 3.8 and Python 3.11. Each run compiles `fabos_core` and `tests`, then executes the complete unittest suite.

During the first real run, the suite exposed test-fixture issues that had previously been hidden because the new Pass 16–18 tests called `migrate()` without first calling the database's `initialize()` method. Those fixtures were corrected.

The same run also exposed an outdated Pass 15-era migration assertion expecting the maximum migration version to remain exactly 35. That assertion was changed to verify the required minimum schema version instead, allowing later migrations to exist.

A further Pass 18 test run exposed missing `customer_id` fields in invoice list/payment-history query results used by customer isolation. Those query projections were corrected.

### Current verification

GitHub Actions successfully completed the Python 3.11 test job after the final Pass 18 isolation fix. The Python 3.8 job was still running at documentation time; its result should be treated as pending until the workflow reports completion.

The workflow provides an ongoing regression check for the existing FabOS architecture and explicitly checks the project's Python 3.8 compatibility target.
