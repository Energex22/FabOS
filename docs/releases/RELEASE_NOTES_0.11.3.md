# FabOS Alpha 0.11.3 — Verified Physical Printing

This release changes one-click printing from optimistic API calls to a verified transaction.

## Before a physical start
FabOS now:
1. Downloads/locates the STL.
2. Slices it through the selected slicer.
3. Validates that the generated G-code contains:
   - Nozzle heat command (M104/M109)
   - Bed heat command (M140/M190)
   - Motion
   - Extrusion
4. Queries OctoPrint and confirms the printer is operational/not already printing.
5. Uploads the G-code.
6. Uses OctoPrint's returned uploaded path instead of assuming the local filename survived unchanged.
7. Verifies that OctoPrint actually selected that file.

## Starting
After the final physical-safety confirmation, FabOS now uses OctoPrint's official:
`POST /api/job {"command":"start"}`

FabOS then polls `/api/job` until OctoPrint itself reports Printing/Paused/Pausing.
Only after that verification does FabOS:
- create a database print job marked Printing,
- set the printer card to Printing,
- report success to the user.

If OctoPrint stays Operational/Idle, refuses the command, has no selected file, or returns
409 Conflict, FabOS reports the actual failure and does NOT create a fake active print job.

## Better diagnostics
The print dialog now visibly moves through:
- G-code validation
- OctoPrint preflight
- Upload/select
- Start command
- Verified physical printing state

This should make it possible to pinpoint whether a future problem is slicing, G-code,
OctoPrint readiness, file selection, or actual printer start.
