import tempfile,unittest,uuid,struct
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_desktop.main import FabOSDesktop
from fabos_desktop.product_print_ui import ProductPrintMixin

def tiny_stl(path):
    header=b"FabOS".ljust(80,b" ")
    raw=bytearray(header+struct.pack("<I",1))
    raw+=struct.pack("<3f",0,0,1)
    for v in [(0,0,0),(10,0,0),(0,10,0)]:
        raw+=struct.pack("<3f",*v)
    raw+=struct.pack("<H",0)
    Path(path).write_bytes(raw)

class CatalogReadinessTests(unittest.TestCase):
 def make(self,td):
  db=Database(td/"x.sqlite3");db.initialize();migrate(db)
  def product(name):
   pid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,name,"verified"));c.commit()
   return pid
  return db,product

 def test_stl_and_gcode_both_count_as_ready(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,product=self.make(td);vault=DesignVaultService(db,td/"vault")
   p1=product("STL Product");p2=product("GCode Product");p3=product("Needs File")
   stl=td/"part.stl";tiny_stl(stl)
   gcode=td/"part.gcode";gcode.write_text("M140 S80\nM104 S235\nG90\nG1 X10 Y10 E1\n",encoding="utf-8")
   vault.import_product_print_files(p1,[stl])
   vault.import_product_print_files(p2,[gcode])
   result=vault.product_print_status_map([p1,p2,p3])
   self.assertTrue(result[p1]["ready"]);self.assertTrue(result[p1]["has_stl"])
   self.assertTrue(result[p2]["ready"]);self.assertTrue(result[p2]["has_gcode"])
   self.assertFalse(result[p3]["ready"])

 def test_saved_gcode_is_persisted_and_preferred(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,product=self.make(td);vault=DesignVaultService(db,td/"vault")
   pid=product("Saved GCode")
   g=td/"saved.gcode";g.write_text("M140 S70\nM104 S225\nG90\nG1 X5 Y5 E1\n",encoding="utf-8")
   status=vault.import_product_print_files(pid,[g])
   self.assertTrue(status["has_gcode"])
   self.assertTrue(Path(status["preferred_gcode"]).exists())

 def test_catalog_ui_methods_exist(self):
  self.assertTrue(hasattr(FabOSDesktop,"_switch_product_view"))
  self.assertTrue(hasattr(FabOSDesktop,"_style_product_tabs"))

 def test_saved_gcode_print_accepts_explicit_path(self):
  import inspect
  sig=inspect.signature(ProductPrintMixin._import_cura_gcode_print)
  self.assertIn("gcode_path",sig.parameters)

if __name__=="__main__":
 unittest.main()
