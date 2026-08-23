# FabOS Alpha 0.12.3 — Cura Slicing Progress Runtime Hotfix

Fixes:
`Could not prepare print: name 'time' is not defined`

The live Cura slicing progress implementation uses `time.monotonic()` to calculate:
- elapsed slicing time
- estimated total slicing time
- estimated time remaining

The 0.12.2 package retained the progress implementation but was missing the `time`
runtime import after the safe-print rebuild.

This release:
- restores `import time`
- verifies `threading` is available for streamed Cura output
- adds a runtime regression test for those dependencies
- keeps all 0.12.2 centered-bed and XY overtravel protection
