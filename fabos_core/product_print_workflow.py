"""FabOS 0.16 Pass 8: unified Product -> Preflight -> Production workflow."""
from dataclasses import dataclass, field

@dataclass
class PrintSelection:
    product_id: str
    product_name: str
    printer_id: str = ""
    order_id: str = ""
    filament_id: str = ""
    source_type: str = ""
    source_file: str = ""
    quantity: int = 1

@dataclass
class PrintWorkflowResult:
    ok: bool
    stage: str
    message: str
    selection: PrintSelection
    preflight: object = None
    job: object = None
    errors: list = field(default_factory=list)

class ProductPrintWorkflow:
    """Single orchestration path for catalog/product printing.

    Existing readiness and production services remain authoritative. This
    layer does not implement a second OctoPrint/Cura integration.
    """
    def __init__(self, preflight, production_service=None):
        self.preflight = preflight
        self.production_service = production_service

    def prepare(self, selection, **checks):
        pf = self.preflight.evaluate(
            selection.product_id, selection.product_name, **checks
        )
        if not pf.ready:
            return PrintWorkflowResult(
                False, "preflight", "Print is not ready", selection,
                preflight=pf, errors=pf.reasons
            )
        return PrintWorkflowResult(
            True, "ready", "Print is ready to start", selection, preflight=pf
        )

    def start(self, prepared, extra_payload=None):
        if not prepared.ok or prepared.stage != "ready":
            return PrintWorkflowResult(
                False, "preflight",
                "Print cannot start until preflight passes",
                prepared.selection, preflight=prepared.preflight,
                errors=prepared.errors
            )
        if self.production_service is None:
            return PrintWorkflowResult(
                False, "service",
                "Production print service is not configured",
                prepared.selection, preflight=prepared.preflight,
                errors=["production_service"]
            )
        payload = {
            "product_id": prepared.selection.product_id,
            "product_name": prepared.selection.product_name,
            "printer_id": prepared.selection.printer_id,
            "order_id": prepared.selection.order_id,
            "filament_id": prepared.selection.filament_id,
            "source_type": prepared.selection.source_type,
            "source_file": prepared.selection.source_file,
            "quantity": prepared.selection.quantity,
        }
        if extra_payload:
            payload.update(extra_payload)
        job = self.production_service.start_print(payload)
        return PrintWorkflowResult(
            True, "started", "Print submitted to production",
            prepared.selection, preflight=prepared.preflight, job=job
        )
