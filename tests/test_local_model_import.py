import tempfile,unittest,uuid,struct
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.products import ProductService
from fabos_core.services.product_print import ProductPrintService
from fabos_desktop.main import FabOSDesktop

def tiny_binary_stl(path,size=10.0):
    header=("FabOS test %.1f"%size).encode().ljust(80,b" ")
    tri=struct.pack("<I",1)
    normal=struct.pack("<fff",0,0,1)
    verts=struct.pack("<fffffffff",0,0,0,size,0,0,0,size,0)
    attr=struct.pack("<H",0)
    Path(path).write_bytes(header+tri+normal+verts+attr)

class DummyMfg:pass

class LocalModelImportTests(unittest.TestCase):
 def test_product_model_import_and_primary_stl(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);db=Database(td/"x.sqlite3");db.initialize();migrate(db)
   pid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("""INSERT INTO products(id,sku,name,category,license_status)
                 VALUES(?,?,?,?,?)""",(pid,"WV-1","Imported Widget","Test","verified"));c.commit()
   vault=DesignVaultService(db,td/"vault")
   a=td/"part_a.stl";b=td/"part_b.stl"
   tiny_binary_stl(a,10);tiny_binary_stl(b,20)
   status=vault.import_product_models(pid,[a,b])
   self.assertTrue(status["ready"])
   self.assertEqual(status["stl_count"],2)
   self.assertEqual(status["primary_name"],"part_a.stl")
   primary=vault.primary_model_asset(status["design_id"])
   self.assertEqual(primary["is_primary"],1)
   self.assertTrue(Path(primary["stored_path"]).exists())

 def test_duplicate_files_stay_deduplicated(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);db=Database(td/"x.sqlite3");db.initialize();migrate(db)
   pid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Duplicate Test","verified"));c.commit()
   vault=DesignVaultService(db,td/"vault");a=td/"same.stl";tiny_binary_stl(a)
   did=vault.ensure_product(pid)
   self.assertTrue(vault.import_file(did,a))
   self.assertFalse(vault.import_file(did,a))
   self.assertEqual(vault.product_model_status(pid)["stl_count"],1)

 def test_product_print_reuses_local_stl_without_website(self):
  with tempfile.TemporaryDirectory() as td:
   td=Path(td);db=Database(td/"x.sqlite3");db.initialize();migrate(db)
   pid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("""INSERT INTO products(id,sku,name,category,license_status,source_url)
                 VALUES(?,?,?,?,?,?)""",(pid,"WV-2","Offline Widget","Test","verified","https://example.invalid/blocked"));c.commit()
   products=ProductService(db);vault=DesignVaultService(db,td/"vault")
   stl=td/"offline.stl";tiny_binary_stl(stl)
   vault.import_product_models(pid,[stl])
   service=ProductPrintService(db,products,vault,DummyMfg(),td/"data")
   path,origin=service.download_model(pid)
   self.assertEqual(origin,"existing")
   self.assertTrue(path.exists())
   self.assertEqual(path.suffix.lower(),".stl")

 def test_catalog_has_local_model_actions(self):
  self.assertTrue(hasattr(FabOSDesktop,"_import_downloaded_product_model"))
  self.assertTrue(hasattr(FabOSDesktop,"_download_product_model_browser"))

if __name__=="__main__":unittest.main()
