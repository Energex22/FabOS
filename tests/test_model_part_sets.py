import tempfile,unittest,uuid,struct
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.model_plate import ModelPlateService
from fabos_desktop.main import FabOSDesktop

def box_stl(path,w,d,h=5.0):
 # 12 triangles for a rectangular box.
 v=[
  (0,0,0),(w,0,0),(w,d,0),(0,d,0),
  (0,0,h),(w,0,h),(w,d,h),(0,d,h)
 ]
 faces=[
  (0,2,1),(0,3,2),(4,5,6),(4,6,7),
  (0,1,5),(0,5,4),(1,2,6),(1,6,5),
  (2,3,7),(2,7,6),(3,0,4),(3,4,7)
 ]
 header=b"FabOS box".ljust(80,b" ")
 raw=bytearray(header+struct.pack("<I",len(faces)))
 for a,b,c in faces:
  raw+=struct.pack("<3f",0,0,0)
  for idx in (a,b,c):raw+=struct.pack("<3f",*v[idx])
  raw+=struct.pack("<H",0)
 Path(path).write_bytes(raw)

class ModelPartSetTests(unittest.TestCase):
 def make_product(self,td):
  db=Database(td/"x.sqlite3");db.initialize();migrate(db)
  pid=str(uuid.uuid4())
  with db.connect() as c:
   c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Fidget Bear","verified"));c.commit()
  vault=DesignVaultService(db,td/"vault")
  return db,pid,vault

 def test_multiple_stls_suggest_part_set_but_do_not_force_it(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,pid,vault=self.make_product(td)
   head=td/"head.stl";body=td/"body.stl";box_stl(head,35,35);box_stl(body,55,45)
   status=vault.import_product_models(pid,[head,body])
   self.assertEqual(status["model_mode"],"single")
   self.assertTrue(status["suggest_part_set"])
   vault.set_model_mode(status["design_id"],"part_set")
   self.assertEqual(vault.product_model_status(pid)["model_mode"],"part_set")

 def test_quantities_create_complete_set_plate(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,pid,vault=self.make_product(td)
   head=td/"head.stl";body=td/"body.stl";arm=td/"arm.stl";leg=td/"leg.stl"
   box_stl(head,35,35);box_stl(body,55,45);box_stl(arm,18,55);box_stl(leg,22,65)
   status=vault.import_product_models(pid,[head,body,arm,leg])
   vault.set_model_mode(status["design_id"],"part_set")
   parts=vault.model_parts(status["design_id"])
   for p in parts:
    name=p["original_name"]
    qty=2 if name in ("arm.stl","leg.stl") else 1
    vault.update_model_part(p["id"],Path(name).stem.title(),qty,True)
   summary=vault.model_set_summary(status["design_id"])
   self.assertEqual(summary["part_count"],4)
   self.assertEqual(summary["piece_count"],6)
   plate=ModelPlateService(vault,td/"data").build_complete_set(pid)
   self.assertEqual(plate["pieces"],6)
   self.assertLessEqual(plate["used_w"],240)
   self.assertLessEqual(plate["used_d"],240)
   self.assertTrue(Path(plate["path"]).exists())
   data=Path(plate["path"]).read_bytes()
   self.assertGreater(len(data),84)
   tri_count=struct.unpack("<I",data[80:84])[0]
   self.assertEqual(tri_count,12*6)

 def test_oversize_set_is_rejected(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw);db,pid,vault=self.make_product(td)
   huge=td/"huge.stl";box_stl(huge,250,40)
   status=vault.import_product_models(pid,[huge])
   vault.set_model_mode(status["design_id"],"part_set")
   with self.assertRaises(ValueError):
    ModelPlateService(vault,td/"data").build_complete_set(pid)

 def test_model_set_ui_is_wired(self):
  self.assertTrue(hasattr(FabOSDesktop,"_manage_product_model_set"))

if __name__=="__main__":unittest.main()
