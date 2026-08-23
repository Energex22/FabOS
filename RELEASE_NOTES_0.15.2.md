# WireVault FabOS Beta 0.15.2 — Cumulative Workflow Polish

## Workspace crash recovery
A single page failure no longer has to take down the workflow.

If Products, Orders, Production, Health, or another workspace fails while building, FabOS now:
- logs the full exception
- keeps the application open
- renders an in-app Workspace Error panel
- shows the actual short error
- offers Retry
- offers Open Logs
- offers Export Diagnostics

This complements the global Tkinter exception logger added in 0.15.0.

## Production Active / History
Production now follows the organizational pattern used by Quotes and Orders.

### Active Production
Contains:
- Queued
- Scheduled
- Printing
- Paused
- Failed

### Production History
Contains:
- Completed
- Cancelled

Completed jobs no longer have to clutter the daily Production workspace.

## Production quick filters
Active Production includes:
- All Active
- Ready
- Printing
- Needs Attention
- Failed

History includes:
- All History
- Completed
- Cancelled

The Production toolbar also displays the number of visible active/history jobs.

## Retry Failed Print
Failed jobs now have a direct `Retry Failed` action in both the Production toolbar and
right-click menu.

FabOS reuses the failed job's:
- Catalog product
- assigned printer
- assigned spool
- best matching saved G-code

The normal print readiness and safety workflow still runs before physical printing.

## Health direct-open actions
System Health now includes an Action column.

Double-clicking or pressing Enter on an actionable Health row opens the place that can fix it:
- Printer / OctoPrint → Printers
- Cura → Settings
- Backup / migration → Backup & Health
- Design Vault / Catalog / G-code → Products
- Filament / packaging / supplies → Filament
- Logging / crash recovery → Logs & Version
- Workflow / Action Center → Dashboard
- Disk / data directory → Settings

## Startup recovery summary
When FabOS detects an unclean shutdown and successfully reconciles active jobs against OctoPrint,
the Dashboard now displays a Startup Recovery card showing how many Production jobs were recovered
and provides a direct Review Production button.

## Old Tk/Tkinter compatibility pass
The desktop source is regression-scanned for the Treeview heading pattern that caused
`value for "-command" missing` on older Tk builds.

No `command=None` / conditional `else None` Treeview-heading patterns remain in this build.

## Existing 0.15.x fixes retained
This is cumulative and includes:
- Products compatibility fix from 0.15.1
- safe asynchronous System Health
- application logging
- diagnostics export
- validated backups
- crash recovery
- Beta self-test
- schema 35
- G-code verification
- packaging/supply inventory
- Analytics ranges
- Action Center
- Print Next
- saved Cura G-code workflow
- production readiness
- QC, invoicing and fulfillment


## Production layout polish
The Production workspace was tightened after testing the new Active/History design at normal
desktop widths:
- narrower fixed-width utility columns
- Product column absorbs extra space
- Selected Job panel receives more minimum width
- permanently visible horizontal Production scrollbar removed
- vertical scrolling retained

This keeps the important job controls and selected-job details visible without wasting a large
strip of the window on horizontal scrolling.
