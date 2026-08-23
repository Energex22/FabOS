import tempfile,unittest,zipfile,configparser,io
from pathlib import Path
from fabos_core.services.cura_integration import CuraIntegrationService

class CuraIntegrationTests(unittest.TestCase):
 def test_bundled_petg_profile(self):
  base=Path(__file__).resolve().parents[1]
  profile=base/"data"/"cura_profiles"/"Vyper PETG.curaprofile"
  self.assertTrue(profile.exists())
  svc=CuraIntegrationService(base)
  global_values,extruder_values=svc.read_curaprofile(profile)
  self.assertEqual(global_values.get("layer_height"),"0.2")
  self.assertEqual(global_values.get("material_bed_temperature"),"80.0")
  self.assertEqual(extruder_values.get("material_print_temperature"),"230")
  self.assertEqual(extruder_values.get("retraction_amount"),"5.5")
  self.assertEqual(extruder_values.get("material_flow"),"82.5")

 def test_cura_gcode_metadata_petg(self):
  with tempfile.TemporaryDirectory() as td:
   g=Path(td)/"test.gcode"
   g.write_text(";TIME:7200\n;Filament used: 10.00m\n",encoding="utf-8")
   svc=CuraIntegrationService(Path(td))
   meta=svc.gcode_metadata(g,"PETG")
   self.assertEqual(meta["estimated_minutes"],120)
   self.assertAlmostEqual(meta["filament_length_m"],10.0)
   self.assertTrue(30 < meta["filament_g"] < 31)

 def test_vyper_machine_volume(self):
  svc=CuraIntegrationService(Path("."))
  self.assertEqual(svc.VYPER_GLOBAL["machine_width"],"245")
  self.assertEqual(svc.VYPER_GLOBAL["machine_depth"],"245")
  self.assertEqual(svc.VYPER_GLOBAL["machine_height"],"260")

if __name__=="__main__":unittest.main()
