import tempfile
import unittest
from pathlib import Path

from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService


class DesignVaultRollbackTests(unittest.TestCase):
    def test_remove_design_deletes_database_rows_and_stored_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            db = Database(Path(temp) / "fabos.db")
            db.initialize()
            migrate(db)
            vault = DesignVaultService(db, temp)
            source = Path(temp) / "part.stl"
            source.write_text("solid part\\nendsolid part\\n", encoding="utf-8")
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO designs(id,product_id,name,current_version) VALUES(?,?,?,?)",
                    ("design-rollback", None, "Rollback Part", 1),
                )
                conn.execute(
                    "INSERT INTO design_versions(id,design_id,version,label) VALUES(?,?,?,?)",
                    ("version-rollback", "design-rollback", 1, "Upload"),
                )
                conn.commit()

            self.assertTrue(vault.import_file("design-rollback", source, make_primary=True))
            asset = vault.assets("design-rollback")[0]
            stored = Path(asset["stored_path"])
            self.assertTrue(stored.exists())

            self.assertTrue(vault.remove_design("design-rollback"))
            self.assertFalse(stored.exists())
            self.assertEqual(vault.assets("design-rollback"), [])
            self.assertIsNone(vault.get("design-rollback"))


if __name__ == "__main__":
    unittest.main()
