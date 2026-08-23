import tempfile,unittest,uuid
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.cura_integration import CuraIntegrationService
from fabos_desktop.main import FabOSDesktop
from fabos_desktop.product_print_ui import ProductPrintMixin

class GCodeLibrary0129Tests(unittest.TestCase):
 def make_product(self,td):
  db=Database(td/"x.sqlite3");db.initialize();migrate(db)
  pid=str(uuid.uuid4())
  with db.connect() as c:
   c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Flexi Lizard","verified"));c.commit()
  return db,pid,DesignVaultService(db,td/"vault")

 def test_profile_hints_extract_cura_metadata(self):
  with tempfile.TemporaryDirectory() as raw:
   p=Path(raw)/"petg.gcode"
   p.write_text(
    ";Generated with Cura_SteamEngine 4.13.1\n"
    ";MATERIAL_TYPE:PETG\n"
    ";MACHINE_NAME:Anycubic Vyper\n"
    ";LAYER_HEIGHT:0.20\n"
    ";NOZZLE_DIAMETER:0.4\n"
    ";TIME:3600\n"
    "M140 S80\nM104 S235\nG90\nG1 X10 Y10 E1\n",encoding="utf-8")
   h=CuraIntegrationService.gcode_profile_hints(p)
   self.assertEqual(h["material"],"PETG")
   self.assertEqual(h["machine"],"Anycubic Vyper")
   self.assertEqual(h["hotend"],235.0)
   self.assertEqual(h["bed"],80.0)
   self.assertEqual(h["layer_height"],0.2)
   self.assertEqual(h["estimated_minutes"],60)

 def test_library_lists_and_deletes_saved_gcode(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,pid,vault=self.make_product(td)
   g=td/"saved.gcode";g.write_text("M140 S80\nM104 S235\nG90\nG1 X5 Y5 E1\n",encoding="utf-8")
   vault.import_product_print_files(pid,[g])
   rows=vault.gcode_library(pid)
   self.assertEqual(len(rows),1)
   self.assertTrue(Path(rows[0]["stored_path"]).exists())
   self.assertTrue(vault.delete_product_gcode(pid,rows[0]["id"]))
   self.assertEqual(vault.gcode_library(pid),[])

 def test_catalog_has_gcode_library_manager(self):
  self.assertTrue(hasattr(FabOSDesktop,"_manage_product_gcode_library"))

 def test_import_print_callback_supports_saved_path(self):
  import inspect
  sig=inspect.signature(ProductPrintMixin._import_cura_gcode_print)
  self.assertIn("gcode_path",sig.parameters)

 def test_manual_import_is_auto_saved_structurally(self):
  source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/product_print_ui.py").read_text(encoding="utf-8")
  self.assertIn("import_product_print_files(product_id,[gcode])",source)
  self.assertIn("Material Mismatch",source)
  self.assertIn("Saved G-code",source)

if __name__=="__main__":
 unittest.main()
