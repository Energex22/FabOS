# FabOS 0.16 — Pass 13
## Production Queue Action Board

Adds a read-only action board over the existing Queue Planner, Decision Engine,
and Next-Action Layer. Each job exposes its next action, status, priority/due
metadata, blockers/warnings, and safe-to-start flag.

The action board never starts hardware, changes job state, assigns hardware,
or bypasses the existing Cura/G-code/OctoPrint pipeline.

New code is Python 3.8 compatible.
