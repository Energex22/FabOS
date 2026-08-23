# FabOS Alpha 0.10.4

- Fixes QC functions accidentally falling outside the ManufacturingMixin class in 0.10.3.
- QC automatically reconciles completed/order-QC jobs into inspection records.
- Printer page no longer displays a stale FabOS product when OctoPrint is idle.
- While OctoPrint is printing or paused, its actual current filename is preferred.
- Active-job fallback now uses the newest matching FabOS job.
- Invoice page now shows uninvoiced orders directly below the invoice table.
- Orders can be invoiced by double-clicking or with Create Selected Invoice.
