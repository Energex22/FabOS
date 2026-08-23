import unittest
from pathlib import Path
from fabos_desktop.main import FabOSDesktop

class BetaUI0150Tests(unittest.TestCase):
    def test_logs_version_page_exists(self):
        self.assertTrue(hasattr(FabOSDesktop,"_build_logs_version_page"))

    def test_callback_exception_handler_exists(self):
        self.assertTrue(hasattr(FabOSDesktop,"_report_callback_exception"))

    def test_health_never_silently_blanks(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/system_ui.py").read_text(encoding="utf-8")
        block=source[source.index("def _system_refresh_health"):source.index("def _system_beta_self_test")]
        self.assertIn("Running diagnostics",block)
        self.assertIn("No checks were returned",block)
        self.assertIn("health_safe()",block)

    def test_health_has_beta_self_test_and_diagnostics(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/system_ui.py").read_text(encoding="utf-8")
        self.assertIn("Run Beta Self-Test",source)
        self.assertIn("Export Diagnostics",source)

    def test_packaging_supply_ui_exists(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/inventory_ui.py").read_text(encoding="utf-8")
        self.assertIn("Packaging & Supplies",source)
        self.assertIn("def _supplies_manager",source)

    def test_system_workspace_contains_logs_version(self):
        self.assertIn("Logs & Version",FabOSDesktop.WORKSPACES["Backup & Health"][1])

if __name__=="__main__":
    unittest.main()
