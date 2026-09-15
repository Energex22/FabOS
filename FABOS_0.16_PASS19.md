# FabOS 0.16 — Pass 19: Fulfillment Boundary

## Scope
Pass 19 hardens the existing fulfillment system for authenticated, role-aware access without replacing the existing fulfillment workflow or schema.

## Implemented

- Extended `FulfillmentService` with optional `AccountService` and `PermissionService` dependencies.
- Added authenticated actor validation for fulfillment access.
- Added customer ownership checks through `customer_accounts` → `customers` → `orders` → `fulfillments`.
- Added `get_for_user()` and `list_for_user()` read boundaries.
- Added `ensure_for_user()` and `save_for_user()` management boundaries.
- Customers can read only fulfillment records belonging to their linked customer and cannot mutate fulfillment.
- Employees and administrators use `fulfillment.read` / `fulfillment.manage` permissions.
- Per-user permission overrides remain enforced through `PermissionService`.
- Application wiring now supplies the existing account and permission services to `FulfillmentService`.
- Existing internal `ensure()` and `save()` methods remain intact for the established desktop/business workflow.
- Existing fulfillment-to-order status behavior remains in the original `save()` business path.

## Security notes

Customer ownership is based on the order's `customer_id`; legacy orders without a customer association are therefore not exposed through customer-facing fulfillment reads. Actor-aware methods require an active authenticated user. Customer mutations are blocked by the permission model because the customer role does not have `fulfillment.manage`.

## Regression coverage

`tests/test_pass19_fulfillment_boundary.py` covers:

- customer isolation for fulfillment reads
- employee/administrator reads
- customer mutation denial
- employee fulfillment management
- fulfillment → order status preservation
- per-user permission override denial
- unlinked customer isolation
- application dependency wiring

## Compatibility

No fulfillment table was duplicated or replaced. The existing fulfillment business logic remains authoritative for desktop/internal workflows. Customer-facing/API code should use the actor-aware methods rather than calling unrestricted internal mutators directly.

## Verification

The repository CI workflow established in Pass 18 should execute the full test suite on Python 3.8 and 3.11 after this pass. Pass 19 is complete only after both CI jobs report success.
