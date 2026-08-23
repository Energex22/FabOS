# Build Status 0.10.1

- Python compile: PASS
- Automated tests: PASS
- Total automated tests: 17
- Uploaded Cura PETG profile parse: PASS
- Cura PETG layer / temperature / retraction / flow settings: PASS
- Cura G-code TIME parsing: PASS
- Cura G-code filament-length → PETG grams conversion: PASS
- Anycubic Vyper 245 × 245 × 260 machine configuration: PASS
- Existing product, Design Vault, quote, order, invoice, printer, inventory and workspace tests: PASS
- Missing UI callback scan: PASS

CuraEngine command execution itself must be acceptance-tested on the Windows 7 workstation,
because Cura 4.13.1 and CuraEngine.exe are installed on that computer rather than in this build environment.
