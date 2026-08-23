# WireVault FabOS Alpha 0.6.0 Engineering Package

Production-oriented foundation for FabOS, kept compatible with Python 3.8 for the Windows 7 desktop path.

Implemented: SQLite schema, event bus, automation engine, plugin lifecycle, audit log, backups, desktop shell, OctoPrint client scaffold, tests, API contract, PRD, security model, plugin SDK, and roadmap.

This is an honest engineering foundation, not a claim that every future module is already a finished commercial product.

## Windows 7
1. Install Python 3.8.10 with Tcl/Tk and pip.
2. Double-click `installer\windows7\Start_FabOS.bat`.
3. Run tests with `installer\windows7\Run_Tests.bat`.

Place prior FabOS exports under `data\import`; the conservative importer creates a report before any migration work.


## 0.4.0 additions

- High-contrast white/light text across ttk comboboxes, tabs and dropdown lists.
- Complete Customers module with search, sorting, details, activity, add/edit/delete protection.


## Upgrade from 0.5.0

1. Close FabOS.
2. Copy your existing `WireVault FabOS Data` folder somewhere safe.
3. Extract this release to a new application folder.
4. Run `installer\windows7\Start_FabOS.bat`.
5. FabOS will continue using the existing data directory and create missing schema objects.

## Production workflow

1. Approve a quote to create an order.
2. Open Production.
3. Select `Create Jobs from Orders`.
4. Assign the Anycubic Vyper and a filament spool.
5. Move the job to Printing, then Completed.
6. When every job for the order completes, the order moves to QC.
