# FabOS Alpha 0.12.8 — Catalog Ready to Print

## Catalog workspace split
Catalog now has two views:
- Ready to Print
- Needs Attention

A product is Ready to Print when FabOS has at least one real local:
- STL file, or
- G-code file

Products with neither are placed in Needs Attention.

## Visible print-file status
The Catalog table includes a Print File column:
- STL Ready
- G-code Ready
- STL + G-code
- Needs File

The selected-product dossier also explains the exact readiness state.

## G-code can be stored with the product
Import / Replace Print File now accepts:
- STL
- G-code / GCO / GC
- 3MF
- STEP

Saved G-code is copied into Design Vault and permanently associated with the Catalog product.

If a product has saved G-code, its Print dialog includes:
`Print Saved G-code`

This reuses the existing verified workflow:
saved G-code → safety check → simultaneous preheat → OctoPrint → verified physical start.

If the product has only G-code and no STL, Automatic Slice is hidden/blocked because there is
nothing for CuraEngine to slice.

## Fast Catalog filtering
Ready/Needs Attention uses one batched Design Vault lookup rather than opening or scanning
every product one at a time.
