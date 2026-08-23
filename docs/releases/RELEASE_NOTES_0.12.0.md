# FabOS Alpha 0.12.0 — Cura Definition Fallback

The working Cura GUI and the CuraEngine executable do not always expose their base
definition files in the same folder on older/nonstandard Windows installs.

FabOS now:
- Searches `%APPDATA%\cura\4.13*` and `%LOCALAPPDATA%\cura\4.13*`.
- Keeps searching the CuraEngine install tree.
- Supports explicitly selecting `fdmprinter.def.json`.
- Supports explicitly selecting `fdmextruder.def.json`.
- Saves those paths in System → Settings → Production.
- Uses those explicit files when slicing, bypassing the missing-resources-folder problem.

The official Cura project identifies these two files as the base machine/extruder
definitions required by Cura's definition system.
