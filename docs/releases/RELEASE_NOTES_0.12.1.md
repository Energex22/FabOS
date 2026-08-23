# FabOS Alpha 0.12.1 — Live Cura Slicing Progress

CuraEngine is now launched as a live streaming process instead of a blocking subprocess.

During Cura slicing the One-Click Print window now displays:
- live slicing percentage
- current CuraEngine stage
- elapsed slicing time
- estimated total slicing time
- estimated time remaining

FabOS reads CuraEngine's own `Progress:` output. The time estimates are calculated from
observed progress and elapsed time, so they improve as the slice advances rather than
showing a made-up fixed duration before Cura has done any work.

The overall percentage maps Cura's per-stage progress into a monotonic 1–99% slicing
estimate. 100% is only shown after CuraEngine actually exits and the G-code file exists.

The existing 15-minute CuraEngine safety timeout remains in place.
