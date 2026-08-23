WORKSPACES = {
    "Dashboard": {"group": "home", "tabs": []},
    "Sales": {"group": "business", "tabs": ["Quotes", "Orders", "Invoices", "Customers"]},
    "Products": {"group": "operations", "tabs": ["Catalog", "Part Sets", "Files", "Needs Attention", "History"]},
    "Production": {"group": "operations", "tabs": ["Active", "Schedule", "QC", "History"]},
    "Printers": {"group": "operations", "tabs": ["Printers", "Filament", "Maintenance"]},
    "Business": {"group": "business", "tabs": ["Overview", "Analytics", "Reports"]},
    "Settings": {"group": "system", "tabs": ["System", "Health", "Backups", "Integrations"]},
}

def get_workspace(name):
    return WORKSPACES.get(name, {})
