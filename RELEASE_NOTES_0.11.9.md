# FabOS Alpha 0.11.9 — Cura 4.13.1 Resource Discovery

## Fix for "Cura resources were not found beside CuraEngine.exe"
FabOS no longer assumes Cura's `resources` directory must sit directly beside CuraEngine.exe.

The Cura integration now recognizes common layouts including:
- `<Cura install>\resources`
- `<Cura install>\share\cura\resources`
- `<Cura install>\share\cura`
- `<Cura install>\lib\cura\resources`
- CuraEngine inside a `bin` or Cura subdirectory
- Nonstandard Cura folders discovered within a bounded search of the selected installation

FabOS specifically verifies both files needed for the base definitions:
- `definitions\fdmprinter.def.json`
- `extruders\fdmextruder.def.json`

## Better diagnostics
The Print dialog now displays `Cura resources detected` underneath CuraEngine.exe.
Before slicing, FabOS performs an installation diagnostic and shows the exact resource
locations it checked if discovery fails.

The configured CuraEngine path may remain:
`D:\Programs\Ultimaker Cura 4.13.1\CuraEngine.exe`

No change to your saved PETG Cura profile is required.
