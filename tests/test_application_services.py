import unittest
from pathlib import Path

class ApplicationServiceWiringTests(unittest.TestCase):
 def test_invoice_and_cura_services_are_initialized(self):
  text=(Path(__file__).resolve().parents[1]/"fabos_core"/"application.py").read_text(encoding="utf-8")
  self.assertIn("self.invoices=InvoiceService(",text)
  self.assertIn("self.cura=CuraIntegrationService(",text)
  self.assertLess(text.index("self.cura=CuraIntegrationService("),text.index("self._install_default_cura_profile()"))

if __name__=="__main__":unittest.main()
