# FabOS Alpha 0.6.0

## Implemented

- Real Production Center
- Automatic print-job creation from approved/new orders
- Default Anycubic Vyper record on fresh databases
- Printer and filament assignment
- Job status transitions and timestamps
- Automatic order move to QC when all print jobs finish
- Color-coded production queue
- Embedded selected-job dossier
- Split Product Catalog with embedded product dossier
- Primary image, licensing, price, time, filament, files and variants in one view
- Cumulative SQLite schema and existing data preservation

## Database upgrades

The application continues using the same SQLite data directory. Existing records
are preserved; missing schema objects are created with `CREATE TABLE IF NOT EXISTS`.
Always keep a backup before replacing application code.
