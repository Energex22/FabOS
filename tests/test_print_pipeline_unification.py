import unittest
from pathlib import Path
from fabos_desktop.product_print_ui import ProductPrintMixin
from fabos_desktop.production_ui import ProductionMixin

class PrintPipelineUnificationTests(unittest.TestCase):
 def test_catalog_print_accepts_production_context(self):
  import inspect
  sig=inspect.signature(ProductPrintMixin._print_selected_product)
  for name in ("product_id","printer_id","spool_id","existing_job_id"):
   self.assertIn(name,sig.parameters)

 def test_production_has_real_start_print_action(self):
  self.assertTrue(hasattr(ProductionMixin,"_production_start_print"))
  text=(Path(__file__).resolve().parents[1]/"fabos_desktop"/"production_ui.py").read_text(encoding="utf-8")
  self.assertIn("self._print_selected_product(",text)

 def test_403_errors_are_contextual(self):
  text=(Path(__file__).resolve().parents[1]/"fabos_core"/"services"/"product_print.py").read_text(encoding="utf-8")
  self.assertIn("MODEL WEBSITE 403 FORBIDDEN",text)
  self.assertIn("MODEL DOWNLOAD 403 FORBIDDEN",text)
  self.assertIn("OCTOPRINT 403 FORBIDDEN DURING G-CODE UPLOAD",text)

if __name__=="__main__":unittest.main()
