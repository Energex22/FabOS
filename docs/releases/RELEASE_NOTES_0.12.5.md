# FabOS Alpha 0.12.5 — Cura-Assisted Printing

## Recommended print path
FabOS now supports a Cura-Assisted workflow alongside automatic CuraEngine slicing.

`Open in Cura / Import G-code`:
1. Collects the exact local STL files for the selected Catalog/Production product.
2. For Part Sets, expands configured quantities into unique temporary STL copies.
3. Opens those individual pieces in the real Cura desktop application.
4. The user arranges and slices them using their normal Anycubic Vyper profile/settings.
5. FabOS asks for the exported G-code.
6. FabOS validates heater commands and XY travel.
7. FabOS checks the physical printer/OctoPrint state.
8. Uploads and selects that G-code in OctoPrint.
9. Requests final confirmation.
10. Starts the physical print, verifies heating, and records/tracks the job.

This path deliberately leaves Cura's placement, machine profile, start G-code, adhesion,
supports, and slicing behavior to the working Cura desktop installation.

## Automatic mode retained
`Automatic Slice (Experimental)` remains available so the direct FabOS slicing engine can
continue to be improved without blocking reliable printing today.

## Part Set behavior
A product such as a flexi model with:
- main body x1
- eye x2

opens Cura with three individual STL objects, not a pre-combined STL. Cura therefore gets
the same kind of object list and placement control as if those STLs were opened manually.

Catalog and Production both use this same assisted workflow.
