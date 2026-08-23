import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService

class DesignWorkspaceTests(unittest.TestCase):
    def test_versions_and_history_methods(self):
        with tempfile.TemporaryDirectory() as td:
            db=Database(Path(td)/"fabos.sqlite3");db.initialize();migrate(db)
            pid=str(uuid.uuid4())
            with db.connect() as c:
                c.execute("INSERT INTO products(id,name) VALUES(?,?)",(pid,"Workspace Product"));c.commit()
            svc=DesignVaultService(db,Path(td))
            did=svc.ensure_product(pid)
            svc.new_version(did)
            self.assertEqual(len(svc.versions(did)),2)
            self.assertEqual(svc.production_history(did),[])
            self.assertIsNone(svc.primary_model_asset(did))

if __name__=="__main__":unittest.main()
