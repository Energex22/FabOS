# FabOS Alpha 0.9.1 — Live OctoPrint Refresh

- Printers page automatically synchronizes OctoPrint every 3 seconds while the page is open.
- Network calls run in a background thread so the Windows UI stays responsive.
- Live state, current OctoPrint filename, print progress, nozzle temperature, bed temperature, elapsed print time and estimated remaining time are displayed.
- Jobs started directly in OctoPrint can still show the current G-code filename even when no FabOS job is matched.
- Matching FabOS jobs are automatically moved to Printing/Paused when OctoPrint reports those states.
- Sync stops automatically when leaving the Printers page.
- Manual Sync Now remains available for diagnostics.
