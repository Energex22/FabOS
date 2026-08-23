# FabOS Alpha 0.12.2 — Safe Centered Vyper Printing

- Centers a generated multi-part product plate around X122.5 / Y122.5 on the Vyper bed.
- Removes FabOS's previous long two-line purge path along the bed edge.
- If the selected Cura profile supplies machine start/end G-code, those values override
  the FabOS fallback.
- The fallback start only establishes units/modes, homes, and resets extrusion.
- Every G-code file is now checked for X/Y overtravel before upload.
- G90/G91 absolute and relative positioning are tracked.
- G0/G00/G1/G01 moves outside 0..245 mm cause a hard stop before OctoPrint receives the file.
- The Print window reports the verified X/Y range after slicing.
