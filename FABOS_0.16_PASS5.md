# FabOS 0.16 Pass 5 — Products Workspace

Built against the current uploaded GitHub export, preserving the user's latest fixes.

Products now has four practical views:
- Ready to Print
- Needs Attention
- Part Sets
- Files

Part Sets is driven by the existing Design Vault model mode, while Files shows
products that have a saved STL and/or G-code asset. Ready/Needs Attention continue
to use the existing print-readiness service as the source of truth.

This pass intentionally does not invent a product-history table yet; a real history
view should be backed by audit/events rather than simply sorting products by date.
