# WireVault FabOS 0.15.0 Beta — Beta Readiness

This release changes the development focus from adding isolated features to making FabOS
reliable as a complete 3D-printing business workflow.

## System Health — blank-page fix and hardening
- Health now uses one safe diagnostic source instead of mixing the old Reliability path
  with the newer Operations Center health path.
- Health runs in a background thread.
- A `CHECKING / Running diagnostics…` row is shown while it works.
- An exception becomes a visible FAIL row instead of an empty panel.
- Health cannot silently render blank; if no checks are returned it displays a diagnostic message.
- Live health now checks:
  - SQLite integrity
  - data directory
  - free disk space
  - backup availability
  - latest-backup validation
  - CuraEngine
  - Cura definition/resource readiness
  - OctoPrint configuration
  - live OctoPrint/printer connectivity
  - database migrations
  - business record access
  - Design Vault
  - error logging
  - crash-recovery state
  - supply inventory
  - G-code verification registry
  - workflow consistency
- System status warnings are clickable and lead directly to Backup & Health.

## Application logging and diagnostics
- Tkinter callback exceptions are captured by FabOS rather than only appearing in the console.
- Errors are written as structured records in `WireVault FabOS Data\Logs\fabos.log`.
- New System → Logs & Version workspace shows:
  - FabOS version
  - database schema
  - Python runtime
  - recent warnings/errors
- Diagnostics Export creates a ZIP containing:
  - version/schema information
  - Health results
  - settings with credentials redacted
  - printer configuration with API keys redacted
  - application log
- The business database itself is deliberately NOT included in the diagnostics ZIP.

## Crash recovery
- FabOS writes a runtime-session marker while open.
- Normal shutdown removes the marker.
- If FabOS/Windows terminates unexpectedly, the next launch detects the unclean session.
- FabOS queries OctoPrint and reconciles attached Production jobs that are still physically
  printing or paused.
- The Action Center and Health surface the recovery event for operator review.

## Backup and recovery hardening
- Shutdown backups can be enabled and are validated after creation.
- Manual backups are validated immediately.
- `Test Latest Backup` verifies:
  - SQLite integrity
  - critical FabOS tables
  - file readability
- Restore continues to create a pre-restore safety backup.
- Database migrations continue to create a safety backup before schema changes.
- Beta self-test creates and validates a temporary backup without altering business records.

## Database upgrade
Schema 35 adds:
- persistent G-code verification records
- packaging/supply inventory
- supply transactions
- runtime state foundation
- Beta/recovery settings

An automated regression test upgrades a schema-34 database to schema 35.

## Persistent G-code verification
FabOS now records verification against the G-code SHA-256 hash.

Verification stores:
- file hash
- product
- printer
- material
- nozzle/bed temperatures
- layer height
- nozzle size
- X/Y envelope
- estimated print time
- estimated filament
- problems
- verification timestamp

If the G-code file changes after verification, its old verification no longer matches and
the file returns to `Not verified`.

The Saved G-code Library displays verification status and provides `Verify Selected`.

Both imported Cura G-code and successful experimental automatic slices update the verification registry.

## Filament and failed-print accounting
Existing safeguards remain:
- insufficient filament blocks physical start
- very low post-print reserve warns
- successful prints deduct usage
- failed prints record estimated waste

## Packaging & supplies inventory
Inventory now includes non-filament supplies:
- boxes
- padded mailers
- bubble wrap
- labels
- magnets
- hardware
- inserts
- other consumables

Each supply tracks:
- category
- unit
- quantity
- unit cost
- low-stock threshold
- transaction history

Low supplies appear in Action Center.

Orders can record packaging usage from the Fulfillment screen and deduct it from supply inventory.

## Packing and fulfillment
Orders retain the full lifecycle:
Accepted → Production → QC → Packing → Shipped

Fulfillment supports:
- carrier
- tracking
- destination
- weight
- package length / width / height
- shipping cost
- packaging inventory usage

Shipping cost updates the invoice total rather than silently remaining outside billing.

## Analytics
Analytics now supports:
- Today
- 7 Days
- 30 Days
- 1 Year
- All Time

It reports:
- paid revenue
- net tracked profit
- margin
- outstanding balance
- failed-print rate
- tracked print hours
- packaging/supply consumption
- current supply inventory value
- product manufacturing profitability
- payment ledger

Recorded supply usage is now included in net tracked business cost.

## Workflow consistency audit
Health checks for state contradictions, including:
- FabOS job says Printing/Paused while printer says Idle/Offline/Error
- shipped order without tracking
- completed order with unfinished Production jobs

## Built-in Beta Readiness Self-Test
System → Backup & Health → `Run Beta Self-Test` performs non-destructive checks for:
- database integrity
- schema version
- database write + rollback
- backup creation + restore validation
- Design Vault availability
- known-good G-code safety parsing
- global search
- diagnostics service
- crash-recovery service
- complete application health

A standalone `RUN_BETA_SELF_TEST.bat` is also included.

## End-to-end regression test
The automated suite now exercises a synthetic business lifecycle:
Customer
→ Quote
→ Approved Order
→ Production Job
→ Print Completion
→ QC
→ Ready
→ Invoice
→ Payment
→ Shipping
→ Shipping-charge balance
→ Final Payment
→ Delivered
→ Completed

## Clean install verification
The release packaging process also starts FabOS against an entirely new temporary data
folder and runs the Beta self-test. That clean-install validation passed for this package.

## Existing major features retained
- Action Center
- Print Next
- notifications
- live printer monitoring
- Pause / Resume / Cancel
- Production automatic completion
- Orders Active / History
- Quotes Active / History
- Catalog Ready / Needs Attention
- saved G-code library
- material-aware G-code selection
- Cura G-code import
- simultaneous bed/hotend preheating
- Product Part Sets
- QC
- invoices/payments
- fulfillment/shipping
- activity journal
- safe order-status undo
- global search / command bar
- card gallery
- setup wizard
- scrollable long panels
- right-click actions and keyboard shortcuts

## Slicer status
The normal Cura desktop → save G-code → Import/Reuse in FabOS workflow remains the
recommended production workflow.

Direct CuraEngine automatic slicing remains available as `Automatic Slice (Experimental)`.
It is intentionally not promoted to production-stable status in this Beta.
