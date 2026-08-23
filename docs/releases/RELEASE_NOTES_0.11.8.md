# FabOS Alpha 0.11.8 — Multi-Part Model Sets

## How FabOS knows Single Model vs Part Set
FabOS no longer assumes every group of STL files is a multi-part product.

Every Catalog product now has an explicit Model Type:
- Single Model
- Part Set

When multiple distinct STL files are imported, FabOS asks:
"Are these separate parts that combine into ONE finished product?"

Yes switches the product to Part Set.
No keeps it as Single Model so multiple STLs can still represent alternate versions/options.
The choice can be changed anytime from Manage Model / Part Set.

## Part Set editor
Each STL receives an editable part record:
- Part Name
- Quantity in one finished product
- Include / exclude from Complete Set

Example:
- Head ×1
- Chest ×1
- Arm ×2
- Leg ×2

Duplicate quantities reuse the same STL; duplicate physical STL files are not required.

## Complete Set plate
For a Part Set, Print now:
1. Reads every included STL.
2. Expands each part by its configured quantity.
3. Calculates each piece footprint.
4. Tests 90-degree rotation where useful.
5. Auto-arranges the pieces with spacing inside the Anycubic Vyper 245 × 245 mm bed.
6. Generates one combined `Complete_Set.stl`.
7. Sends that plate through Cura → G-code validation → OctoPrint → verified physical start.

If FabOS cannot arrange the requested pieces inside the Vyper build area, it stops before
slicing and explains that the set needs to be split or quantities reduced.

## Preview
Manage Model / Part Set includes `Preview Complete Set on Vyper`.
It reports every part placement, rotation, total pieces, used plate area, and generated plate path.

Catalog and Production both use the same Part Set definition and complete-set print pipeline.
