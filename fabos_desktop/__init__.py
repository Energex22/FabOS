# Pass 20 desktop hardening is loaded before main.py imports the system mixin.
from fabos_desktop import system_ui_v20  # noqa: F401
# Pass 21 consolidates the operator catalog and adds Fabvex storefront controls.
from fabos_desktop import catalog_storefront_v21  # noqa: F401
from fabos_desktop import catalog_storefront_v21_refresh  # noqa: F401
# Pass 22 adds the internal administrator control center and configurable business settings.
from fabos_desktop import admin_panel_v22  # noqa: F401
