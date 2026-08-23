# FabOS Beta Readiness Checklist

## Before real customer production
1. Open System → Backup & Health.
2. Run Health Check.
3. Click Run Beta Self-Test.
4. Resolve every FAIL.
5. Review WARN items and confirm they are expected.
6. Test Latest Backup.
7. Confirm the physical printer shows live OctoPrint data.
8. Confirm the correct filament spool is selected and weighed/updated.
9. Verify a saved G-code file for the printer/material you intend to use.
10. Run one known test print before depending on the workflow for a customer deadline.

## Recommended production path
Catalog / Production
→ select product/order/printer/spool
→ use verified saved Cura G-code or Import Cura G-code
→ FabOS safety + filament checks
→ simultaneous preheat
→ OctoPrint
→ physical print
→ automatic Production completion
→ QC
→ Packing
→ Shipping
→ History

## When something fails
1. Open System → Logs & Version.
2. Review the latest ERROR/WARNING.
3. Open Backup & Health.
4. Run Health Check.
5. Export Diagnostics.
6. Keep the diagnostics ZIP; it contains no database and redacts API credentials.
