# FabOS Alpha 0.11.6 — Unified Catalog / Production Printing

## 403 errors now identify the real source
FabOS no longer reports a generic `HTTP Error 403: Forbidden`.

A 403 while reading a model website is reported as:
- MODEL WEBSITE 403 FORBIDDEN

A protected/session-only model download is reported as:
- MODEL DOWNLOAD 403 FORBIDDEN

An OctoPrint G-code upload authorization failure is reported as:
- OCTOPRINT 403 FORBIDDEN DURING G-CODE UPLOAD

The OctoPrint preflight also verifies the configured API key via `/api/currentuser`.
Actual file endpoints remain the authority for FILES_UPLOAD/FILES_SELECT permissions
because OctoPrint permissions may be inherited through user groups.

## Production can now physically print
Production previously managed assignments/status and attached G-code but had no true
one-click physical print action.

Selected production jobs now show:
- Start Print
- Open Product
- Assign Printer / Spool

Start Print launches the same verified physical-print pipeline used by Catalog and
preselects the production job's assigned printer and filament spool.

After OctoPrint actually reports Printing and heater response is confirmed, FabOS updates
the EXISTING production job instead of creating a duplicate standalone print job.

## Model-site restrictions
FabOS does not bypass website authentication, CAPTCHA, paywalls, or session-restricted
downloads. If a source blocks automated download, import the legally obtained STL into
Design Vault once. All later Catalog and Production prints use that cached local model.
