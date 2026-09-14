# FabOS 0.16 — Pass 12
## Startup Repair + Production Next-Action Layer

### Repair
- Restored the missing `ProductionQueuePlanner` import that caused startup `NameError`.
- Ensured Production Queue Planner, Decision Engine, and Next-Action services are initialized by the application.

### New
- Added `ProductionNextAction`, a deterministic advisory layer that reports:
  - blocked
  - monitor
  - assign_printer
  - preflight
- Added a small UI formatter for displaying the next action.
- Added regression tests for next-action behavior and application startup wiring.

### Safety
The next-action layer is advisory. `safe_to_start=True` means the next safe step is printer preflight; it does not start a physical print and does not bypass the existing OctoPrint/Cura/G-code safety pipeline.

### Compatibility
New code is written for Python 3.8 compatibility.
