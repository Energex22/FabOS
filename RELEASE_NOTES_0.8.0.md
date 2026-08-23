# FabOS Alpha 0.8.0 — Printer Automation & Live Production

## Printer Center
- Dedicated printer page with live-style printer cards.
- Connection mode per printer: Simulation or OctoPrint.
- OctoPrint URL/API key setup.
- Printer status, current/next job, progress, nozzle/bed temperatures and last-seen time.
- Manual OctoPrint sync for Windows 7-friendly operation.

## Simulation Mode
- Run the complete production workflow without touching the physical printer.
- Start a scheduled job, advance it in 10% increments, and complete it.
- Completion records manufacturing data, deducts assigned filament, and creates QC.

## Production automation
- Failed-print reason capture.
- One-click reprint while retaining the failed job in history.
- Filament deduction is guarded so a completed job is not deducted twice.
- Existing manufacturing learning continues to improve estimates.

## Safety / compatibility
Windows 7 is no longer supported by Microsoft. Keep FabOS and OctoPrint on a trusted
local network and do not expose either directly to the public internet.
