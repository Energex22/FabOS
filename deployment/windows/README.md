# FabOS on Windows

Backup and host-hardening helpers for the FabOS API server.

The Caddy configuration, production launcher scripts, pre-launch checklist, and
the domain/HTTPS walkthrough live in FabOS-Web under `deployment/windows/`,
because Caddy's site root is the storefront build:
https://github.com/Energex22/FabOS-Web/tree/main/deployment/windows

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

## Backup verification can be run offline without modifying the live data directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\Verify-FabOS-Backup.ps1 -Archive C:\FabVex\Data\Backups\fabos-backup-YYYYMMDD-HHMMSS.zip
```

The verifier rejects archive path traversal, extracts only into a temporary directory, opens the bundled SQLite database read-only, and runs `PRAGMA integrity_check`. It does not restore or overwrite production data.

Restore test

A backup is not considered verified until a ZIP can be extracted and its `fabos.sqlite3` can be opened by SQLite. Test restores should be performed against a separate temporary FabOS data directory, never over the live database.

Do not commit backup ZIP files to Git.

## Production host protection

Always set, on every deployment path:

- `FABOS_API_HOST=127.0.0.1` so the API is not directly exposed to the network.

The remaining variables depend on **which server process is running**, because
the two entry points read different settings. See the table in the repository
README under "Two API entry points".

When running `python -m fabos_core.cli serve` (FastAPI):

- `FABOS_ALLOWED_HOSTS=your-public-domain` to reject unexpected HTTP Host headers.
- `FABOS_CORS_ORIGINS=https://your-public-domain` using the exact storefront
  origin. Only needed when the storefront is served from a different origin than
  the API. In the standard Caddy deployment the storefront and API share one
  hostname, requests are same-origin, and CORS does not apply.
- `FABOS_API_DOCS=false` to keep the generated API documentation private.

If more than one public hostname is intentionally served, list them comma-separated. Do not use a wildcard unless the deployment genuinely requires it.

When running `python -m fabos_api.server` (Waitress, used by
`Start-FabVex-Production.ps1` in FabOS-Web):

- `FABOS_API_ALLOW_ORIGIN=https://your-public-domain`, or leave it unset for a
  same-origin deployment where it has no effect.
- `FABOS_API_THREADS` to size the request thread pool. Defaults to 8.

`FABOS_CORS_ORIGINS`, `FABOS_ALLOWED_HOSTS`, and `FABOS_API_DOCS` are **not read
by this server** and setting them there does nothing. Host-header filtering on
this path has to come from Caddy, which only answers for the hostnames in its
site blocks.
