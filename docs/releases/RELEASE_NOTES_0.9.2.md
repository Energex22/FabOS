# FabOS Alpha 0.9.2 — Product Print Pipeline & Web Image Repair

## Web image repair
- Expanded source-page image discovery beyond Open Graph metadata.
- Recognizes Twitter images, image_src links, common JSON/JavaScript image fields, srcset/data-srcset and lazy-loaded image attributes.
- Candidate URLs are verified as actual image responses before saving.
- Successful real images are promoted to primary and generated placeholder cards are removed.

## Print directly from Products
- New Print button on the Product Catalog.
- Reuses an existing Design Vault model automatically.
- For verified-license products, attempts to discover and download publicly exposed STL/3MF/ZIP files from the official source page.
- Downloaded models are imported into Design Vault and become the cached source for all future prints.
- Runs PrusaSlicer console in the background using the saved/configured INI profile.
- Uploads generated G-code to the chosen OctoPrint printer.
- Requires a final build-plate/filament confirmation before starting the physical printer.
- Creates a FabOS print-job record and assigns the selected filament spool.
- Existing live OctoPrint sync tracks the print afterward.

## Source-site limitations
FabOS does not bypass sign-in requirements, JavaScript-only download controls, CAPTCHAs, or other access restrictions. If a host does not expose a legitimate direct model file, download/import it once through Design Vault; repeat prints then use the cached model automatically.
