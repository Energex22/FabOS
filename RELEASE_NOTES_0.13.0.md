# FabOS Alpha 0.13.0 — Production Print Readiness

The Production Queue now understands the Catalog's local STL/G-code state.

## New Production `Print File` column
Each job shows:
- G-code Ready
- STL Ready
- Needs Attention

## Material-aware G-code selection
For an assigned Production job, FabOS compares saved G-code with the assigned filament.
A matching saved G-code is selected automatically.

If a job is assigned PLA but the only saved G-code identifies itself as PETG, FabOS does not
call the job ready. It shows Needs Attention instead of making the operator discover the
mismatch after clicking Print.

If an STL is also available, the job remains ready because it can be sliced for the assigned
material.

## Start Print integration
Starting from Production passes the best matching saved G-code into the normal Print window.
That G-code is preselected, while the operator can still choose another saved file.

Jobs without a usable print file show `Fix Print File`, which opens the Catalog product so the
missing STL/G-code can be corrected.
