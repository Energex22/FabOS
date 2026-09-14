"""Canonical destinations for product print-readiness fixes."""
TARGETS = {
    "printer": ("Printers", "Printers"),
    "filament": ("Printers", "Filament"),
    "maintenance": ("Printers", "Maintenance"),
    "files": ("Products", "Files"),
    "parts": ("Products", "Part Sets"),
    "gcode": ("Products", "Files"),
    "order": ("Sales", "Orders"),
    "bed": ("Settings", "System"),
    "idle": ("Production", "Active"),
}

def target_for(check_key):
    return TARGETS.get(check_key)
