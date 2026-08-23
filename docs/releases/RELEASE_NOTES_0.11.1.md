# FabOS Alpha 0.11.1 — Settings Center

## System → Settings is now functional
Centralized configuration for:
- Business/shop name, owner, email, phone and address.
- Customer-update signature.
- Invoice prefix.
- Invoice due days.
- Default sales-tax percentage.
- Quote-validity window.
- Machine hourly cost.
- Packaging cost.
- Target margin.
- Default slicer.
- CuraEngine path.
- PETG Cura profile.
- Low-filament threshold.
- Reorder forecast window.
- Backup retention.

## Settings now drive workflows
- New invoices use the configured invoice prefix.
- New invoices use the configured due-date window.
- Default sales tax is applied to newly created invoices.
- Printable invoice exports include the configured shop identity/contact info.
- Customer updates append the configured signature.
- Backup retention uses the configured value.
- Existing manufacturing/inventory/Cura settings remain synchronized.

Existing records are preserved. New defaults only affect newly created invoices and future generated communications.
