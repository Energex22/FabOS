from dataclasses import dataclass, field

@dataclass
class ReadinessItem:
    key: str
    label: str
    ok: bool
    severity: str = "error"
    detail: str = ""

@dataclass
class ProductReadiness:
    product_id: str = ""
    product_name: str = ""
    items: list = field(default_factory=list)

    @property
    def ready(self):
        return bool(self.items) and not any(
            not x.ok and x.severity == "error" for x in self.items
        )

    @property
    def errors(self):
        return [x for x in self.items if not x.ok and x.severity == "error"]

    @property
    def warnings(self):
        return [x for x in self.items if not x.ok and x.severity == "warning"]

    def add(self, key, label, ok, detail="", severity="error"):
        self.items.append(ReadinessItem(key, label, ok, severity, detail))
        return self

    def summary(self):
        return "READY TO PRINT" if self.ready else "NOT READY"

def evaluate_product(product_id, product_name, *,
                     stl_available=False, gcode_available=False,
                     part_set=False, parts_complete=True,
                     bed_compatible=True, printer_online=False,
                     printer_idle=True, filament_available=True,
                     gcode_valid=True, maintenance_ok=True,
                     order_allowed=True):
    r = ProductReadiness(product_id, product_name)
    r.add("files", "Printable files", stl_available or gcode_available,
          "No STL or G-code is attached")
    if part_set:
        r.add("parts", "Part set", parts_complete,
              "One or more required parts are missing")
    r.add("bed", "Printer bed", bed_compatible,
          "Model/G-code exceeds the configured print area")
    r.add("printer", "Printer online", printer_online,
          "Selected printer is offline")
    r.add("idle", "Printer available", printer_idle,
          "Printer is already running another job")
    r.add("filament", "Filament", filament_available,
          "Required filament is unavailable")
    if gcode_available:
        r.add("gcode", "G-code validation", gcode_valid,
              "G-code failed validation")
    r.add("maintenance", "Printer maintenance", maintenance_ok,
          "Printer requires maintenance", severity="warning")
    r.add("order", "Order status", order_allowed,
          "The attached order is not currently printable")
    return r
