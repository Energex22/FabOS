# FabOS Alpha 0.10.3 Hotfix

Fixes a service-wiring regression in 0.10.2:
- Restores `self.invoices = InvoiceService(...)`.
- Restores `self.cura = CuraIntegrationService(...)`.
- Ensures Cura exists before the default Cura profile installer runs.
- Adds a regression test so future builds cannot silently omit these application services.

No database migration or data reset is required. Existing FabOS data remains intact.
