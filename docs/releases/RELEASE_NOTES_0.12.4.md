# FabOS Alpha 0.12.4 — Cura Edge Tolerance

Fixes false safety failures such as:
`X245.02 Y196.02`

CuraEngine can emit coordinates a few hundredths of a millimeter beyond an exact
machine-width number because of floating-point/toolpath rounding.

FabOS now has two limits:
- Nominal Vyper bed: 0.00–245.00 mm
- Hard safety tolerance: -0.50–245.50 mm

Moves inside the nominal bed pass normally.
Moves only slightly outside nominal but still within the 0.50 mm tolerance pass with
an explicit edge-rounding warning.
Moves beyond the hard tolerance are still blocked before OctoPrint upload.

This does not enlarge or move the model itself. Part-set placement is still generated
inside the Vyper bed. The tolerance applies only to the final Cura-generated G-code.
