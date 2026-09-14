# FabOS 0.16 Pass 8 — Product Print Workflow

Added:
- One ProductPrintWorkflow orchestration path for catalog/product printing.
- Product -> preflight -> production flow.
- Failed preflight returns structured reasons and never starts a print.
- Successful requests are handed to the existing production print service.
- Product print selection UI with printer, optional order, and quantity.
- Existing OctoPrint/Cura/G-code services remain authoritative.
