# FabOS 0.16 — Pass 11: Production Queue Decision Engine

Adds a centralized, deterministic READY/BLOCKED decision layer for production jobs.
It explains blockers and warnings without contacting or starting printers. READY only
hands the job to the existing OctoPrint/G-code/heater safety pipeline.
