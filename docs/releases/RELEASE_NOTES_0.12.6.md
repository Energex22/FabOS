# FabOS Alpha 0.12.6 — Print Workflow Polish

## Cura workflow
- FabOS no longer launches Cura.
- `Import Cura G-code` is the recommended manual-slicer path.
- Slice normally in Cura, save the G-code, then select that file in FabOS.
- Automatic CuraEngine slicing remains available as `Automatic Slice (Experimental)`.

## Simultaneous preheating
Before physical print start, FabOS reads the hotend and bed targets from the G-code.
It sends non-waiting M140 (bed) and M104 (hotend) targets together before starting the job.
The normal Cura M190/M109 commands in the G-code may then wait for both heaters to reach
temperature without forcing one heater to remain cold until the other finishes.

## Production completion
OctoPrint live synchronization now recognizes successful completion using OctoPrint's
completion/time-left signals. A verified finished job is automatically:
- marked Completed,
- given actual runtime,
- charged against filament inventory,
- recorded for manufacturing learning,
- advanced to QC when it was the last active print for an order.

The Production page now polls OctoPrint in a background thread and refreshes every few seconds,
so the queue can change from Printing to Completed without pressing Refresh.

## Catalog order attachment
The Product Print dialog includes `Attach Print to Order`.
- Personal/no-order prints remain supported.
- Selecting an order links the print job to it.
- If that order already has a queued/scheduled job for the same Catalog product, FabOS
  reuses that production job instead of creating a duplicate.
- Existing Production jobs keep their order locked when opened through Production.

## Faster Print dialog
Opening the Product Print dialog no longer scans the Cura installation or resources tree.
Those slower checks only run if `Automatic Slice (Experimental)` is actually selected.
