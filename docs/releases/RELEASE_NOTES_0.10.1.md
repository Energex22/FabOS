# FabOS Alpha 0.10.1 — Cura 4.13.1 Integration

## Cura is now the default slicer
- One-click Product Print defaults to Cura.
- PrusaSlicer remains available as an optional legacy slicer.
- Automatic detection of common Cura 4.13.1 CuraEngine.exe locations.
- Cura 4.13.1 resources are discovered from the installed Cura folder.

## Your Anycubic Vyper PETG profile
- The supplied `PETG Cura.curaprofile` is bundled as `Vyper PETG.curaprofile`.
- On first run FabOS copies it into the persistent `WireVault FabOS Data\Cura Profiles` folder.
- PETG spools automatically select that profile.
- A different `.curaprofile` can be selected for each material and FabOS remembers it.

## CuraEngine profile handling
Cura `.curaprofile` files contain setting overrides rather than a standalone CuraEngine
machine definition. FabOS extracts the global and extruder overrides and layers them over:
- Cura 4.13.1's own fdmprinter definition
- Cura 4.13.1's own fdmextruder definition
- Anycubic Vyper 245 × 245 × 260 mm machine settings
- 0.4 mm nozzle / 1.75 mm filament settings

## One-click print flow
Product → cached/downloaded STL → CuraEngine → G-code → OctoPrint → final physical-start confirmation.

FabOS reads Cura's G-code TIME and filament-length metadata. Filament grams are estimated
from 1.75 mm filament length using a material density table (PETG 1.27 g/cm³, PLA 1.24 g/cm³,
etc.) and are then available for production estimates and inventory tracking.

## Important
Automatic CuraEngine slicing currently uses STL input. 3MF files can stay in Design Vault,
but use/import an STL version for one-click CuraEngine printing in this release.
