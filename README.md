# FabOS 0.16 — Pass 13
## Production Queue Action Board

Adds a read-only action board over the existing Queue Planner, Decision Engine,
and Next-Action Layer. Each job exposes its next action, status, priority/due
metadata, blockers/warnings, and safe-to-start flag.

The action board never starts hardware, changes job state, assigns hardware,
or bypasses the existing Cura/G-code/OctoPrint pipeline.

## Customer HTTP API

FabOS now includes an official FastAPI + Uvicorn HTTP boundary for the separate
FabOS-Web customer frontend. The API delegates to the existing FabOS services;
it does not create a second database or business-logic layer.

Start it locally with:

`python -m fabos_core.cli serve`

The local API listens on `http://127.0.0.1:8000` by default. Customer-web CORS
origins can be configured with `FABOS_CORS_ORIGINS` as a comma-separated list.

Implemented customer-facing routes include public catalog reads, customer
authentication, customer profile reads/updates, quote reads/submission, and
order reads/submission. Customer ownership is enforced server-side and browser
submitted totals are not authoritative. Internal production jobs, printer data,
QC records, invoices, audit records, and the internal order dossier are not
exposed by the customer API.

Custom-work file upload is now supported through the dedicated multipart quote-request endpoint. STL, 3MF, OBJ, STEP/STP files up to 25 MB are staged, validated, imported into Design Vault, and linked to the quote without exposing internal filesystem paths. Online payment sessions and provider webhooks are also wired through the backend payment boundary.

See `docs/CUSTOMER_API_CONTRACT.md` for the route and data contract.

New code is Python 3.8 compatible.
