# FabOS Alpha 0.10.0 — Invoices & Payments

## Business workspace
The Invoices tab is now a working module instead of a placeholder.

## Order → Invoice
- Create an invoice directly from a selected order.
- Customer, order number, quoted line items and subtotal are reused automatically.
- FabOS generates invoice numbers automatically.
- Duplicate active invoices for the same order are prevented.
- Configurable payment due period.

## Invoices
- Search and sortable columns.
- Status filter: Open, Partial, Paid, Void.
- Total, paid amount and balance due shown separately.
- Tax, shipping, discount and invoice notes.
- Detailed invoice view with quoted items and payment history.
- Printable/browser invoice export stored under the FabOS data directory.

## Payments
- Record partial or full payments.
- Payment method, reference and notes.
- Automatic Partial/Paid invoice state.
- When a Ready order's invoice becomes fully paid, the order becomes Completed.
- Paid/partially paid invoices cannot be silently voided.

No customer, quote, order, manufacturing or Design Vault data is replaced.
