# FabOS 0.16 — Pass 9: Catalog Print Integration & Copy Queue

Pass 9 makes the Product Print window a true front door into the existing production pipeline and adds quantity-aware follow-up jobs.

## Changes
- Product Print now exposes **Copies to Print**.
- The first selected copy is launched through the existing OctoPrint/G-code safety path.
- Additional copies are automatically queued as separate Production jobs after the first print successfully starts. They are queued, not auto-started.
- Production jobs persist a `quantity` field for future scheduling/analytics.
- Added `ProductionService.queue_additional_copies()` so copy creation is centralized.
- Removed a duplicate G-code verification call in the Product Print path.
- Existing printer, heater, G-code, filament, and final confirmation safeguards remain authoritative.

## Safety
Additional copies never bypass the existing printer preflight or final confirmation because they remain queued Production jobs.
