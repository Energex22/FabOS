# FabOS Alpha 0.11.5 — PrinterAutomationService Wiring Hotfix

Fixes a regression introduced in 0.11.4 where `sync_octoprint` was accidentally
moved outside `PrinterAutomationService` by an indentation error.

- Restores `PrinterAutomationService.sync_octoprint`.
- Keeps the new offline / printer-response / heater verification logic from 0.11.4.
- Adds a regression test against the actual service class so this method cannot
  silently disappear in a future patch.

No database reset or migration is required.
