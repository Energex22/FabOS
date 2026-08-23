import tempfile,unittest
from pathlib import Path
from fabos_core.services.cura_integration import CuraIntegrationService

class CuraEdgeToleranceTests(unittest.TestCase):
 def test_245_02_is_rounding_warning_not_failure(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"edge.gcode"
   p.write_text("G90\nG1 X245.02 Y196.02\n",encoding="utf-8")
   r=CuraIntegrationService.gcode_xy_bounds(p)
   self.assertTrue(r["valid"])
   self.assertEqual(len(r["violations"]),0)
   self.assertEqual(len(r["warnings"]),1)
   self.assertAlmostEqual(r["max_x"],245.02,places=3)

 def test_245_49_is_allowed_but_warned(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"edge2.gcode"
   p.write_text("G90\nG1 X245.49 Y100\n",encoding="utf-8")
   r=CuraIntegrationService.gcode_xy_bounds(p)
   self.assertTrue(r["valid"])
   self.assertEqual(len(r["warnings"]),1)

 def test_245_51_is_blocked(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"bad.gcode"
   p.write_text("G90\nG1 X245.51 Y100\n",encoding="utf-8")
   r=CuraIntegrationService.gcode_xy_bounds(p)
   self.assertFalse(r["valid"])
   self.assertEqual(len(r["violations"]),1)

 def test_large_overtravel_still_blocked(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/"bad2.gcode"
   p.write_text("G90\nG1 X260 Y100\n",encoding="utf-8")
   r=CuraIntegrationService.gcode_xy_bounds(p)
   self.assertFalse(r["valid"])

if __name__=="__main__":
 unittest.main()
