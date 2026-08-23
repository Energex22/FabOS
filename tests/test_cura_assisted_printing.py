import tempfile,unittest,uuid,struct
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.products import ProductService
from fabos_core.services.product_print import ProductPrintService
from fabos_core.services.cura_integration import CuraIntegrationService
from fabos_desktop.product_print_ui import ProductPrintMixin

def box_stl(path,w=10,d=10,h=2):
 v=[(0,0,0),(w,0,0),(w,d,0),(0,d,0),(0,0,h),(w,0,h),(w,d,h),(0,d,h)]
 faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
 raw=bytearray(b"FabOS".ljust(80,b" ")+struct.pack("<I",len(faces)))
 for a,b,c in faces:
  raw+=struct.pack("<3f",0,0,0)
  for i in (a,b,c):raw+=struct.pack("<3f",*v[i])
  raw+=struct.pack("<H",0)
 Path(path).write_bytes(raw)

class DummyMfg:pass

class CuraAssistedTests(unittest.TestCase):
 def test_cura_gui_discovery_from_engine_folder(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);install=td/"Ultimaker Cura 4.13.1";install.mkdir()
   engine=install/"CuraEngine.exe";engine.write_bytes(b"x")
   gui=install/"Cura.exe";gui.write_bytes(b"x")
   svc=CuraIntegrationService(td/"data")
   self.assertEqual(svc.find_cura_gui(str(engine)),gui)

 def test_part_quantities_become_unique_cura_files(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db=Database(td/"x.sqlite3");db.initialize();migrate(db)
   pid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Flexi Test","verified"));c.commit()
   products=ProductService(db);vault=DesignVaultService(db,td/"vault")
   body=td/"body.stl";eye=td/"eye.stl";box_stl(body,30,20);box_stl(eye,4,4)
   status=vault.import_product_models(pid,[body,eye]);vault.set_model_mode(status["design_id"],"part_set")
   for p in vault.model_parts(status["design_id"]):
    qty=2 if p["original_name"]=="eye.stl" else 1
    vault.update_model_part(p["id"],Path(p["original_name"]).stem,qty,True)
   service=ProductPrintService(db,products,vault,DummyMfg(),td/"data")
   paths=service.cura_assisted_models(pid)
   self.assertEqual(len(paths),3)
   self.assertEqual(len(set(str(p) for p in paths)),3)
   self.assertTrue(all(Path(p).exists() for p in paths))

 def test_ui_has_assisted_workflow(self):
  self.assertTrue(hasattr(ProductPrintMixin,"_cura_assisted_print"))

if __name__=="__main__":
 unittest.main()
