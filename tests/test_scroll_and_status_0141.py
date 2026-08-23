import unittest
from pathlib import Path
from fabos_desktop.main import FabOSDesktop

class ScrollAndStatus0141Tests(unittest.TestCase):
    def test_scrollable_helper_exists(self):
        self.assertTrue(hasattr(FabOSDesktop,"_scrollable_frame"))

    def test_action_center_scrolls_and_is_not_capped(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/main.py").read_text(encoding="utf-8")
        block=source[source.index("def _build_action_center"):source.index("def _open_action_item")]
        self.assertIn("_scrollable_frame",block)
        self.assertNotIn("[:12]",block)

    def test_notifications_scroll(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/main.py").read_text(encoding="utf-8")
        block=source[source.index("def _show_notifications"):source.index("def _bind_global_shortcuts")]
        self.assertIn("_scrollable_frame",block)

    def test_warning_footer_is_explicit(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/main.py").read_text(encoding="utf-8")
        block=source[source.index("def _refresh_system_footer"):source.index("def _build_activity_page")]
        self.assertIn("click for details",block)
        self.assertNotIn("Ready •",block)

    def test_footer_opens_system_health(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/main.py").read_text(encoding="utf-8")
        self.assertIn('self.system_status_label.bind("<Button-1>",lambda _e:self.show_page("Backup & Health"))',source)

    def test_system_health_has_scrollbars(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/system_ui.py").read_text(encoding="utf-8")
        self.assertIn("health_v=ttk.Scrollbar",source)
        self.assertIn("health_h=ttk.Scrollbar",source)

if __name__=="__main__":
    unittest.main()
