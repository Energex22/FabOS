import unittest
from fabos_desktop.main import FabOSDesktop
from fabos_desktop.invoice_ui import InvoiceMixin

class InvoiceMixinWiringTests(unittest.TestCase):
 def test_invoice_mixin_is_on_desktop(self):
  self.assertTrue(issubclass(FabOSDesktop, InvoiceMixin))
  self.assertTrue(hasattr(FabOSDesktop, "_build_invoices_page"))
  self.assertTrue(hasattr(FabOSDesktop, "_refresh_invoices"))
  self.assertTrue(hasattr(FabOSDesktop, "_invoice_create_ready"))
  self.assertTrue(hasattr(FabOSDesktop, "_invoice_payment"))

if __name__=="__main__":unittest.main()
