# FabOS Alpha 0.11.7 — Local Model Import

## One-time browser download workflow
For websites that block automated downloads:
1. Select the product in Catalog.
2. Click `Download Model in Browser`.
3. Download the STL normally from the source website.
4. Return to FabOS and click `Import / Replace Model`.
5. Select one or multiple STL/3MF/STEP files.

FabOS copies the selected files into its persistent Design Vault and permanently associates
them with the Catalog product.

## Model Ready
The Catalog dossier now shows:
- `Model: Not imported`
- or `Model: Ready ✓ — filename.stl`

When an STL is ready, the main product action changes to `Print`.

Catalog printing and Production Start Print both reuse the same locally stored STL, so FabOS
does not contact the model website again for that product.

## Multiple files
Products may contain multiple model files. FabOS stores all unique files and de-duplicates
identical files by SHA-256. The first imported STL becomes the preferred primary printable model.

3MF and STEP may be stored in Design Vault too, but the automated CuraEngine path still
requires an STL in this release.
