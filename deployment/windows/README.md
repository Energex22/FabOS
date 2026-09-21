# FabOS on Windows

These helpers assume FabOS uses the default persistent data directory:

`%USERPROFILE%\WireVault FabOS Data`

Set `FABOS_DATA_DIR` if you use another location.

## Manual backup

From an elevated PowerShell or a normal account with access to the data directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\windows\backup.ps1
```

The backup utility uses SQLite's online backup API so the database is copied consistently while FabOS is running. It then archives the remaining persistent data (including the Design Vault) into the same timestamped ZIP.

By default, the wrapper keeps the newest 14 backups:

```powershell
powershell -ExecutionPolicy Bypass -File .\deployment\windows\backup.ps1 -Keep 30
```

## Scheduled backup

Use Windows Task Scheduler to run the PowerShell command once per day. Recommended settings:

- Run whether the user is logged on or not.
- Run with the least privileges needed to read the FabOS data directory.
- Trigger daily during a low-traffic period.
- Configure the task to stop if it runs for an unusually long time.
- Keep at least 14 local backup archives.

Local backups are not a complete disaster-recovery strategy. Periodically copy a verified backup to a separate physical disk or other storage location.

## Restore test

A backup is not considered verified until a ZIP can be extracted and its `fabos.sqlite3` can be opened by SQLite. Test restores should be performed against a separate temporary FabOS data directory, never over the live database.

Do not commit backup ZIP files to Git.
