# FabOS Alpha 0.11.0 — Backup & Health Center

## Automatic protection
- FabOS creates one automatic startup backup per day.
- Existing migration backups remain intact.
- Manual backups can be created at any time.
- Backup retention is capped at the newest 30 when creating manual backups.

## Restore
- System → Backup & Health lists restore points with date/time and size.
- Restore Selected verifies the chosen SQLite backup before restoring it.
- FabOS creates a pre-restore safety backup automatically.
- The UI instructs you to restart FabOS after a restore so every module reloads cleanly.

## Health Check
Built-in checks now report:
- SQLite database integrity.
- FabOS data-directory availability.
- Free disk space.
- Backup availability.
- Cura/CuraEngine configuration.
- OctoPrint printer configuration.
- Database migration count.
- Counts for core business records.

## System workspace
A new Backup & Health tab lives beside Settings, Automation and Plugins.
This release focuses on protecting the growing FabOS database before additional modules are added.
