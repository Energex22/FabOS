# FabOS Alpha 0.12.9 — Saved G-code Library

## Product G-code Library
Each Catalog product now has a reusable Saved G-code Library.

FabOS extracts useful hints from Cura-style G-code when available:
- Material
- Printer / machine name
- Nozzle temperature
- Bed temperature
- Layer height
- Nozzle size
- Estimated print time
- Cura/generator information

Catalog includes `Manage Saved G-code` where stored files can be reviewed or deleted.

## Smarter Print screen
When a product has multiple saved G-code files, the Print screen now provides a Saved G-code
selector instead of silently choosing whichever file happened to be newest.

Labels include useful information such as:
`Flexi_Lizard_PETG.gcode • PETG • 235/80°C • 4h 24m`

## Material compatibility warning
FabOS compares the material hint inside the selected saved G-code against the filament spool
selected in the Print screen.

Example:
- Saved G-code: PETG
- Loaded spool: PLA

FabOS warns before starting because the temperatures embedded in that G-code may be wrong.
The operator may cancel or deliberately override the warning.

## Imported G-code becomes reusable automatically
When `Import Cura G-code` is used, FabOS now copies that validated G-code into the product's
Design Vault automatically. The next time that Catalog product is printed, the file appears
in its Saved G-code Library and can be selected directly.

Design Vault's SHA-256 duplicate detection prevents the same G-code from being stored repeatedly.
