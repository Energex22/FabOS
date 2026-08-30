---
name: testing-fabos-desktop
description: How to launch and E2E-test the WireVault FabOS Tkinter desktop app on the X display
---

# Testing FabOS Desktop

- Stdlib-only Python Tkinter app; no pip installs needed (only `python3-tk` OS package).
- Launch on the VNC display: `DISPLAY=:0 python3 -m fabos_desktop.main` from the repo root, then maximize with `DISPLAY=:0 wmctrl -r "FabOS" -b add,maximized_vert,maximized_horz` (window title is "WireVault FabOS").
- Data dir is `~/WireVault FabOS Data` (SQLite `fabos.sqlite3`, JSON logs in `Logs/fabos.log`). Inspect via python3's sqlite3 module (`sqlite3` CLI is not installed). Delete the dir for a fresh DB.
- Golden path: Inventory → Filament → "+ Add Spool"; Business → Customers → "+ Add Customer"; Business → Quotes → "+ New Quote" (needs a customer + catalog product); select quote → "Approve & Create Order"; Production → "Create Jobs from Orders" → select job → Assign (printer + spool) → Start → Complete; order status becomes `qc` in Business → Orders.
- Workspace pages render inside an error-recovery wrapper: any Tk exception in a page builder shows a "Workspace Error" panel with Retry/Open Logs/Export Diagnostics; the full traceback is appended to `~/WireVault FabOS Data/Logs/fabos.log` with the page name.
- Dashboard cards/metrics are built at page-build time and may render with a 1–2s delay; wait before screenshotting.
- Global Search: type in the topbar entry and press Enter; results open in a "FabOS Search" toplevel window.
- QC flow: Production → QC tab → "Inspect / Edit"; checking all checklist items and passing QC sets the order to `ready`.
- Toplevel dialogs with canvas-based scrolling don't respond to the mouse wheel — drag their scrollbar instead.

## Devin Secrets Needed
None.
