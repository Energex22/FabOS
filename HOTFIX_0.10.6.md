# FabOS Alpha 0.10.6 — Invoice Analytics & Payment-State Fix

- Analytics now includes paid invoice revenue, outstanding invoice balance and paid invoice count.
- A Payment Ledger tab shows actual recorded payments by invoice/order/customer.
- Manufacturing profitability remains available on its own Analytics tab.
- Invoice state is reconciled from the payments ledger before display/void decisions.
- Paid/partial invoice voiding now explains the real reason it is blocked.
- The old hard-coded "void selected unpaid invoice" wording is removed.
- A stale invoices.paid_cents/status value is repaired automatically from payment rows.
