import unittest
from pathlib import Path

class CatalogHeadingCompat0151Tests(unittest.TestCase):
    def test_non_sortable_catalog_heading_does_not_pass_command_none(self):
        source=Path(__file__).resolve().parents[1].joinpath("fabos_desktop/main.py").read_text(encoding="utf-8")
        start=source.index('headings={"name":"Product"')
        end=source.index('label="ready product"',start)
        block=source[start:end]
        self.assertNotIn("command=(lambda",block)
        self.assertNotIn("else None",block)
        self.assertIn('self.product_table.heading(col,text=heading_text)',block)

if __name__=="__main__":
    unittest.main()
