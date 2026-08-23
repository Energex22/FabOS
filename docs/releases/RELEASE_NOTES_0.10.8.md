# FabOS Alpha 0.10.8 — Fulfillment & Order Workspace

## Fulfillment
- Local Pickup or Shipping per order.
- Pickup statuses: Pending, Ready for Pickup, Picked Up.
- Shipping statuses: Pending, Packed, Shipped, Delivered.
- Carrier, tracking number, destination and actual shipping cost.
- Paid + fulfilled orders can move to Completed automatically.

## Order Control Center
- Rebuilt from the stable 0.10.6 base.
- Compact sortable Orders list and Order Workspace.
- Next Action progresses Production → QC → Invoice → Payment → Fulfillment → Complete.
- Fulfillment is visible directly in the selected order dossier.

## Structural verification
- Order workspace methods are verified on CommerceMixin.
- Order dossier is verified on OrderService.
