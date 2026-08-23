# FabOS Alpha 0.14.0 — Operations Center & Workflow Polish

This release is a broad usability pass focused on making FabOS behave like a connected shop operating system instead of a collection of separate pages.

## Dashboard / Action Center
- Dashboard is now an Action Center focused on what needs attention today.
- Alerts include offline/non-responsive printers, failed prints, jobs missing printer/spool assignments, jobs missing printable files, pending QC, orders ready to pack/ship, overdue orders, quotes awaiting approval/expired, unpaid/overdue invoices, low filament, and Catalog products missing STL/G-code.
- Dashboard refreshes automatically.
- Notification bell shows persistent unread alerts and opens the exact related workspace.
- Notifications reset cleanly after an issue is resolved so the same issue can alert again if it returns.

## Print Next
- New `PRINT NEXT` workflow chooses the earliest runnable production job.
- Requires an assigned idle printer, assigned spool, compatible print file, and enough estimated filament.
- Passes the existing Production job into the normal verified Print workflow rather than creating duplicate work.

## Smarter printers
- Rich printer cards show live file/job, temperatures, elapsed/remaining time, order, and assigned filament.
- Pause/Resume, Cancel Print, and Open Active Job controls are available from the Printers workspace.
- Cancelling through FabOS records the failed job, estimates consumed filament/waste, and logs the activity.

## Automatic workflow progression
- Existing OctoPrint completion → Production complete → QC flow is retained.
- QC completion continues moving orders to Ready.
- Payment no longer skips fulfillment: paying a Ready order does not mark it Completed before delivery/pickup.
- Delivered/Picked Up + paid invoice completes the order.
- Shipped orders remain in Order History as designed.

## Notifications and activity history
- New notifications table and live notification bell.
- New System → Activity workspace.
- Print starts/completions, failed prints, QC changes, fulfillment updates, invoice payments, and manual order status changes are journaled.
- Ctrl+Z / `Undo Last Safe Action` can revert the most recent supported order-status change.

## Global search / command bar
- Search results now open the selected FabOS record with double-click or Enter.
- Search includes Design Vault print files (STL/G-code).
- Commands include `print <product>`, `print next`, `health`, and `unpaid invoices`.

## Catalog usability
- Existing Ready to Print / Needs Attention separation remains.
- New Card View / Card Gallery gives a visual product chooser with images, readiness, price, Details and Print buttons.
- Product dossier includes a file drop/import target.
- If a TkDnD-compatible Tk build is available, STL/G-code can be dropped directly; otherwise the same target opens the normal file picker.
- Saved G-code Library now has background `Verify Selected` for XY bounds, material, temperatures, layer height and time.

## Filament intelligence and inventory
- Print confirmation checks estimated filament against the selected spool.
- Insufficient filament blocks the print before OctoPrint start.
- Very low post-print reserve gives a confirmation warning.
- Successful jobs continue to deduct actual/estimated consumption automatically.
- Failed/cancelled prints estimate consumed filament from printer progress (or a configurable fallback) and record it as waste.
- Failed-print material and machine costs are tracked as negative profit instead of disappearing from profitability.

## Orders, packing and shipping
- Order dossier now shows a lifecycle strip: Accepted → Production → QC → Packing → Shipped.
- Fulfillment records package weight plus length × width × height.
- Shipping cost flows into the linked invoice total.
- Fulfillment status is reflected in Action Center and Order History.
- Orders and Production now have practical right-click menus.

## Profitability
- Analytics adds tracked net profit, margin, and fulfillment shipping cost.
- Failed-print waste contributes to tracked costs.
- Existing per-product manufacturing profitability and manufacturing learning remain intact.

## Setup and health
- New Setup Wizard guides Business → Printer → OctoPrint → Cura → Materials → Catalog readiness.
- System Health now includes Action Center readiness.
- Sidebar system status is live instead of a static `Core online` label.
- Notification and system-health refreshes run in background threads to avoid freezing the Tkinter interface.

## Keyboard shortcuts
- Ctrl+F — global search
- Ctrl+P — print selected product/job, or Print Next elsewhere
- Ctrl+N — quick add
- Ctrl+Z — undo latest supported safe action
- F5 — refresh current workspace

## Notes
- Automatic CuraEngine slicing remains available but experimental.
- Importing trusted Cura-generated G-code remains the recommended production path while the automatic slicer continues to mature.
- Native Tkinter does not include file drag/drop. FabOS enables it automatically only when a compatible TkDnD layer is present; click-to-import always works.
