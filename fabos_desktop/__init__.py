# Pass 20 desktop hardening is loaded before main.py imports the system mixin.
from fabos_desktop import system_ui_v20  # noqa: F401
