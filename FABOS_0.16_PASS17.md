# FabOS 0.16 — Pass 17

## Controlled order lifecycle + customer data isolation

Pass 17 hardens the existing OrderService without replacing the existing order, fulfillment, payment, production, or customer architecture.

### Implemented

- Added explicit order lifecycle transition rules for the statuses already represented by the current order workspace:
  - pending → confirmed / cancelled
  - confirmed → in_production / cancelled
  - in_production → ready / cancelled
  - ready → shipped / completed / cancelled
  - shipped → completed
  - completed and cancelled are terminal
- Order status changes now require an authenticated actor and the `order.manage` permission.
- Customer accounts can read only orders belonging to their linked customer record.
- Customer order listing is isolated to the linked customer.
- Employees and administrators retain permitted order-wide access through the existing RBAC layer.
- Missing customer association does not expose an order to customer accounts.
- Existing unauthenticated `set_status(order_id, status)` calls are no longer accepted; callers must provide the actor identity.
- Existing `list`, `get`, and `dossier` behavior remains available for internal/business-layer use.
- Application wiring now passes the existing AccountService and PermissionService into OrderService.

### Architecture boundary

`AuthService` establishes identity → `PermissionService` establishes capability → `OrderService` enforces order lifecycle and customer ownership → existing payment/fulfillment/production systems remain authoritative for their domains.

No new order schema or duplicate payment/fulfillment system was introduced.

### Tests

Added `tests/test_pass17_order_access.py` covering customer isolation, employee/administrator reads, customer mutation denial, valid/invalid lifecycle transitions, terminal-state protection, and actor-required status changes.

Tests were committed but not executed through a repository test runner in this pass, so no test-pass claim is made.
