# FabOS Alpha 0.7.1 — Product Dossier Callback Fix

- Restores the missing `_manage_product_images` compatibility callback used by the split Product Dossier.
- Restores `_load_primary_product_image` so the embedded dossier uses the same preferred-image logic as Product Preview.
- Keeps the existing image manager, automatic web-image sync, placeholder replacement, and Product Details behavior.
- Static callback scan reports no unresolved private UI method calls.
- Graphical smoke test opens Products, Customers, Quotes, Orders, Production, Design Vault, and QC.
- All six automated tests pass.

This release does not change the database schema and is safe to run against the same `WireVault FabOS Data` directory used by 0.7.0.
