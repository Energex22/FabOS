import unittest
from fabos_core.services.cura_integration import CuraIntegrationService

class CuraProgressTests(unittest.TestCase):
 def test_progress_parser(self):
  p=CuraIntegrationService._cura_progress("Progress:slice:42:100")
  self.assertEqual(p[0],"slice");self.assertEqual(p[1],42.0);self.assertEqual(p[2],100.0)

 def test_progress_parser_ignores_normal_log(self):
  self.assertIsNone(CuraIntegrationService._cura_progress("Loading /tmp/model.stl"))

if __name__=="__main__":unittest.main()
