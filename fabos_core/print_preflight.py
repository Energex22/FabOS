"""FabOS 0.16 unified print preflight coordinator."""
from dataclasses import dataclass, field

@dataclass
class PreflightResult:
    ready: bool
    product_id: str = ""
    product_name: str = ""
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    failed_keys: list = field(default_factory=list)

class PrintPreflight:
    def __init__(self, readiness, production_service=None):
        self.readiness = readiness
        self.production_service = production_service

    def evaluate(self, product_id, product_name, **checks):
        result = self.readiness(product_id, product_name, **checks)
        failures = list(result.errors)
        return PreflightResult(
            ready=result.ready,
            product_id=product_id,
            product_name=product_name,
            reasons=[x.detail or x.label for x in failures],
            warnings=[x.detail or x.label for x in result.warnings],
            failed_keys=[x.key for x in failures],
        )

    def start(self, preflight, job_payload):
        if not preflight.ready:
            raise RuntimeError("Print preflight failed")
        if self.production_service is None:
            raise RuntimeError("Production print service is not configured")
        return self.production_service.start_print(job_payload)
