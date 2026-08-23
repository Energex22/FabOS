import tempfile,unittest,uuid
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.production import ProductionService
from fabos_desktop.main import FabOSDesktop

class Cumulative0152Tests(unittest.TestCase):
    def make_db(self,td):
        db=Database(Path(td)/"fabos.sqlite3");db.initialize();migrate(db)
        return db

    def test_production_active_history_split(self):
        with tempfile.TemporaryDirectory() as td:
            db=self.make_db(td)
            pid=str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Widget","verified"))
                for status in ("queued","printing","failed","completed","cancelled"):
                    c.execute("INSERT INTO print_jobs(id,product_id,status) VALUES(?,?,?)",
                              (str(uuid.uuid4()),pid,status))
                c.commit()
            svc=ProductionService(db)
            active={r["status"] for r in svc.list_jobs(group="active")}
            history={r["status"] for r in svc.list_jobs(group="history")}
            self.assertEqual(active,{"queued","printing","failed"})
            self.assertEqual(history,{"completed","cancelled"})

    def test_page_error_recovery_exists(self):
        self.assertTrue(hasattr(FabOSDesktop,"_render_workspace_error"))

    def test_production_tabs_and_retry_exist(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/production_ui.py").read_text(encoding="utf-8")
        self.assertIn("Active Production",source)
        self.assertIn("Production History",source)
        self.assertIn("def _production_retry_failed",source)
        self.assertIn("Needs Attention",source)

    def test_health_open_actions_exist(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/system_ui.py").read_text(encoding="utf-8")
        self.assertIn("def _system_health_target",source)
        self.assertIn("def _system_open_health_item",source)
        self.assertIn("'action'",source)

    def test_no_treeview_heading_command_none_patterns(self):
        import re
        desktop=Path(__file__).resolve().parents[1]/"fabos_desktop"
        combined="\n".join(p.read_text(encoding="utf-8") for p in desktop.glob("*.py"))
        heading_calls=re.findall(r"\.heading\((?:[^()]|\([^()]*\))*\)",combined,re.S)
        bad=[call for call in heading_calls if "command=None" in call or "else None" in call]
        self.assertEqual(bad,[])
        self.assertNotIn("if sortable else None",combined)

    def test_recovery_summary_is_visible_on_dashboard(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/main.py").read_text(encoding="utf-8")
        self.assertIn("Startup Recovery",source)
        self.assertIn("Review Production",source)

if __name__=="__main__":
    unittest.main()
