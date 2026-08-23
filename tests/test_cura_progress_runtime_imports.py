import unittest
import fabos_core.services.cura_integration as cura_module
from fabos_core.services.cura_integration import CuraIntegrationService

class CuraProgressRuntimeImportTests(unittest.TestCase):
    def test_live_progress_runtime_dependencies_exist(self):
        self.assertTrue(hasattr(cura_module,"time"))
        self.assertTrue(callable(cura_module.time.monotonic))
        self.assertTrue(hasattr(cura_module,"threading"))
        self.assertTrue(callable(cura_module.threading.Thread))

    def test_progress_parser_still_operates(self):
        result=CuraIntegrationService._cura_progress("Progress:slice:25:100")
        self.assertEqual(result,("slice",25.0,100.0))

if __name__=="__main__":
    unittest.main()
