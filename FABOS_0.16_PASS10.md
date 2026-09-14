# FabOS 0.16 — Pass 10: Production Queue Intelligence

## Added
- Central `ProductionQueuePlanner` for active-job filtering and deterministic queue ordering.
- Priority-aware next-job selection.
- Duplicate active-job detection by product/order.
- Queue summary metrics: active, queued, running, blocked.
- Reusable desktop queue-summary helper.
- Regression tests for queue behavior.

## Design
This pass is deliberately non-networked. It does not start or cancel printers and does
not replace OctoPrint safety/preflight. It gives Catalog, Production, and future automation
a single queue-planning layer instead of duplicating queue rules in individual screens.
