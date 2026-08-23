"""FabOS 0.16 workspace consolidation adapter."""
from .workspace_ui import WorkspaceTabs

WORKSPACE_MAP = {
    "Sales": {"Quotes": "Quotes", "Orders": "Orders",
              "Invoices": "Invoices", "Customers": "Customers"},
    "Products": {"Catalog": "Products", "Part Sets": "Products",
                 "Files": "Products", "Needs Attention": "Products",
                 "History": "Products"},
    "Production": {"Active": "Production", "Schedule": "Production",
                   "QC": "QC", "History": "Production"},
    "Printers": {"Printers": "Printers", "Filament": "Inventory",
                 "Maintenance": "Printers"},
    "Business": {"Overview": "Dashboard", "Analytics": "Analytics",
                 "Reports": "Analytics"},
}

def legacy_page(workspace, tab):
    return WORKSPACE_MAP.get(workspace, {}).get(tab)

def build_tabs(parent, workspace, on_tab):
    tabs = WorkspaceTabs(parent)
    for title in WORKSPACE_MAP.get(workspace, {}):
        tabs.add(title, lambda f, t=title: on_tab(f, workspace, t))
    return tabs
