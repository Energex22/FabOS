# FabOS Alpha 0.12.7 — Active Orders & Order History

## Orders now mirror the Quotes workflow
The Orders workspace now has:
- Active Orders
- Order History

Active Orders contains work that still needs shop attention:
- New
- Production
- QC
- Ready / fulfillment preparation

Order History contains:
- Shipped
- Delivered
- Picked Up
- Completed
- Cancelled

An order moves out of Active as soon as its fulfillment status becomes `shipped`.
It does not need to wait until the carrier marks it delivered.

## Fulfillment-aware history
The history view does not rely only on the order.status field. It also reads fulfillment
state, so a shipped/delivered/picked-up package cannot remain mixed into active shop work.

The Status column displays the meaningful fulfillment state where appropriate:
- Shipped
- Delivered
- Picked Up

## Shipping lifecycle
Saving fulfillment as `shipped` also records the order lifecycle as shipped.
Delivered/picked-up orders become fully Completed automatically when their invoice is paid.
If billing is still incomplete, they remain in History with the actual Delivered/Picked Up
fulfillment state rather than returning to Active.

Each tab has its own relevant Status filter and record count.
