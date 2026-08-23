import tempfile,unittest
from pathlib import Path
from fabos_core.services.product_print import ProductPrintService

class ProductPrintTests(unittest.TestCase):
 def test_find_prusaslicer_configured_path(self):
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'prusa-slicer-console.exe';p.write_bytes(b'x')
   self.assertEqual(ProductPrintService.find_prusaslicer(None,str(p)),p)

if __name__=='__main__':unittest.main()
