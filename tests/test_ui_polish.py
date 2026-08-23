import unittest
from pathlib import Path

class UIPolishTests(unittest.TestCase):
 def test_catalog_is_compact_and_dashboard_clickable(self):
  base=Path(__file__).resolve().parents[1]
  text=(base/"fabos_desktop"/"main.py").read_text(encoding="utf-8")
  self.assertIn('columns = ("name", "category", "print_ready", "price", "time", "status")',text)
  self.assertNotIn('columns = ("sku", "name", "category", "designer", "license", "status", "price", "time", "filament")',text)
  self.assertIn('self._bind_dashboard_link(card, target)',text)
  self.assertIn('self._product_context_menu',text)

if __name__=="__main__":unittest.main()
