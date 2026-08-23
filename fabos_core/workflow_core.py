from dataclasses import dataclass, field
from typing import List

@dataclass
class ReadinessCheck:
    key: str
    label: str
    passed: bool
    detail: str = ""

@dataclass
class PrintReadiness:
    checks: List[ReadinessCheck] = field(default_factory=list)
    @property
    def ready(self):
        return bool(self.checks) and all(c.passed for c in self.checks)
    @property
    def failures(self):
        return [c for c in self.checks if not c.passed]
    def add(self, key, label, passed, detail=""):
        self.checks.append(ReadinessCheck(key, label, passed, detail))
        return self
    def summary(self):
        if self.ready:
            return "READY TO PRINT"
        return "Cannot print: " + "; ".join(
            f"{c.label}: {c.detail}" for c in self.failures
        )

def build_print_readiness(printer_online, octoprint_connected, printer_idle,
                          gcode_available, gcode_valid, bed_compatible,
                          filament_available, maintenance_ok=True,
                          order_allowed=True):
    return (PrintReadiness()
        .add("printer_online", "Printer", printer_online, "Printer is offline")
        .add("octoprint", "OctoPrint", octoprint_connected, "OctoPrint unavailable")
        .add("idle", "Current job", printer_idle, "Printer already has an active job")
        .add("gcode", "G-code", gcode_available, "No G-code assigned")
        .add("gcode_valid", "G-code validation", gcode_valid, "G-code failed validation")
        .add("bed", "Bed dimensions", bed_compatible, "G-code exceeds printer bed")
        .add("filament", "Filament", filament_available, "Required filament unavailable")
        .add("maintenance", "Maintenance", maintenance_ok, "Maintenance required")
        .add("order", "Order", order_allowed, "Order is not currently allowed to print"))

def transition_allowed(current, target):
    graph = {
        "quote": {"awaiting_payment", "cancelled"},
        "awaiting_payment": {"ready_for_production", "cancelled"},
        "ready_for_production": {"scheduled", "in_production", "cancelled"},
        "in_production": {"qc", "cancelled"},
        "qc": {"packaging", "in_production", "cancelled"},
        "packaging": {"ready_to_ship"},
        "ready_to_ship": {"shipped"},
        "shipped": {"completed"},
        "waiting": {"scheduled", "queued", "cancelled"},
        "scheduled": {"queued", "cancelled"},
        "queued": {"preparing", "cancelled"},
        "preparing": {"printing", "failed", "cancelled"},
        "printing": {"completed", "paused", "failed", "cancelled"},
        "paused": {"printing", "failed", "cancelled"},
        "completed": {"qc"},
        "failed": {"queued", "cancelled"},
    }
    return target in graph.get(str(current), set())
