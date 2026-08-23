import tempfile,unittest,uuid,struct
from pathlib import Path
from fabos_core.db.database import Database
from fabos_core.db.migrations import migrate
from fabos_core.services.design_vault import DesignVaultService
from fabos_core.services.model_plate import ModelPlateService
from fabos_core.services.cura_integration import CuraIntegrationService

def box_stl(path,w,d,h=5):
 v=[(0,0,0),(w,0,0),(w,d,0),(0,d,0),(0,0,h),(w,0,h),(w,d,h),(0,d,h)]
 faces=[(0,2,1),(0,3,2),(4,5,6),(4,6,7),(0,1,5),(0,5,4),(1,2,6),(1,6,5),(2,3,7),(2,7,6),(3,0,4),(3,4,7)]
 raw=bytearray(b"FabOS".ljust(80,b" ")+struct.pack("<I",len(faces)))
 for a,b,c in faces:
  raw+=struct.pack("<3f",0,0,0)
  for i in (a,b,c):
   raw+=struct.pack("<3f",*v[i])
  raw+=struct.pack("<H",0)
 Path(path).write_bytes(raw)

class SafeCenteredPrintingTests(unittest.TestCase):
 def test_complete_set_centered(self):
  with tempfile.TemporaryDirectory() as raw:
   td=Path(raw)
   db=Database(td/"x.sqlite3");db.initialize();migrate(db)
   pid=str(uuid.uuid4())
   with db.connect() as c:
    c.execute("INSERT INTO products(id,name,license_status) VALUES(?,?,?)",(pid,"Test Set","verified"))
    c.commit()
   vault=DesignVaultService(db,td/"vault")
   a=td/"a.stl";b=td/"b.stl"
   box_stl(a,40,30);box_stl(b,60,50)
   status=vault.import_product_models(pid,[a,b])
   vault.set_model_mode(status["design_id"],"part_set")
   result=ModelPlateService(vault,td/"data").build_complete_set(pid)
   self.assertAlmostEqual(result["center_x"],122.5,places=3)
   self.assertAlmostEqual(result["center_y"],122.5,places=3)
   self.assertGreaterEqual(result["min_x"],0)
   self.assertLessEqual(result["max_x"],245)
   self.assertGreaterEqual(result["min_y"],0)
   self.assertLessEqual(result["max_y"],245)

 def test_absolute_and_relative_safe_moves(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"safe.gcode"
   p.write_text("G90\nG1 X10 Y10\nG1 X220 Y230\nG91\nG1 X5 Y5\n",encoding="utf-8")
   r=CuraIntegrationService.gcode_xy_bounds(p)
   self.assertTrue(r["valid"])
   self.assertEqual(r["max_x"],225.0)
   self.assertEqual(r["max_y"],235.0)

 def test_absolute_overtravel_is_blocked(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"bad.gcode"
   p.write_text("G90\nG1 X10 Y10\nG1 X260 Y30\n",encoding="utf-8")
   r=CuraIntegrationService.gcode_xy_bounds(p)
   self.assertFalse(r["valid"])
   self.assertEqual(r["violations"][0]["line"],3)
   self.assertEqual(r["violations"][0]["x"],260.0)

 def test_relative_overtravel_is_blocked(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"bad_relative.gcode"
   p.write_text("G90\nG1 X240 Y100\nG91\nG1 X10\n",encoding="utf-8")
   r=CuraIntegrationService.gcode_xy_bounds(p)
   self.assertFalse(r["valid"])
   self.assertEqual(r["violations"][0]["x"],250.0)

 def test_old_edge_purge_removed(self):
  start=CuraIntegrationService.VYPER_GLOBAL["machine_start_gcode"]
  self.assertNotIn("Y200",start)
  self.assertNotIn("E15",start)
  self.assertNotIn("E30",start)
  self.assertIn("G28",start)

if __name__=="__main__":
 unittest.main()
