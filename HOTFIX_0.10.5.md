# FabOS Alpha 0.10.5 — Invoice UI Wiring Hotfix

The Invoice screen implementation existed in prior builds, but `InvoiceMixin` was
accidentally omitted from the final `FabOSDesktop` inheritance list during later UI merges.

This release:
- Restores InvoiceMixin to FabOSDesktop.
- Restores the Invoices page, invoice table, uninvoiced-orders list, payment actions,
  charge editing, export and void actions.
- Adds a regression test that verifies the real FabOSDesktop class exposes all key
  invoice methods.

No database migration or reset is required.
