# FabOS Alpha 0.11.4 — Printer Power & Response Detection

## Why this release
OctoPrint can report a connection as "Operational" even though that alone does not prove
the physical printer is powered and actively responding. FabOS previously trusted that
state too much.

## New three-level printer check
Before a print is prepared, FabOS now separately verifies:
1. OctoPrint server is online (`/api/server`).
2. OctoPrint's printer/serial connection is open (`/api/connection`).
3. The printer firmware is actually responding with fresh temperature data.

FabOS sends harmless `M105` temperature-report requests and verifies that OctoPrint receives
fresh temperature history afterward. A stale "Operational" state without a fresh firmware
response is reported as:

`PRINTER NOT RESPONDING`

Closed, Offline and Error connection states are reported as:

`PRINTER OFFLINE/DISCONNECTED`

## Better timeout messages
Generic `<urlopen error timed out>` messages are translated into the stage that failed:
- OctoPrint server check
- Printer connection check
- Printer firmware probe
- G-code upload
- File selection
- Physical print start
- Heating verification

## Physical power verification
After OctoPrint reports Printing, FabOS now checks that heater targets appear and that the
nozzle or bed temperature actually begins to rise. If OctoPrint starts the software job but
the printer has no heater power, FabOS reports:

`PRINTER POWER/HEATER RESPONSE NOT CONFIRMED`

## Printers page
Live OctoPrint synchronization now checks `/api/connection` too. Closed/Error connections
show Offline, and stale temperature history shows `Printer Not Responding` instead of
misleading `Operational`.
