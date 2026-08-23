import unittest
from fabos_core.services.printer_automation import PrinterAutomationService

class PrinterAutomationWiringTests(unittest.TestCase):
 def test_sync_octoprint_is_real_service_method(self):
  self.assertTrue(hasattr(PrinterAutomationService,"sync_octoprint"))
  self.assertTrue(callable(getattr(PrinterAutomationService,"sync_octoprint",None)))

if __name__=="__main__":unittest.main()
