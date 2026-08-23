import unittest
from fabos_desktop.main import FabOSDesktop

class WorkspaceNavigationTests(unittest.TestCase):
    def test_workspace_groups(self):
        self.assertEqual(FabOSDesktop.WORKSPACES["Products"][0], "Catalog")
        self.assertEqual(FabOSDesktop.WORKSPACES["Analytics"][0], "Business")
        self.assertEqual(FabOSDesktop.WORKSPACES["Invoices"][0], "Business")
        self.assertEqual(FabOSDesktop.WORKSPACES["Printers"][0], "Production")
        self.assertEqual(FabOSDesktop.WORKSPACES["Filament"][0], "Inventory")

if __name__ == "__main__":
    unittest.main()
