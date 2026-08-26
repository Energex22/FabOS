import unittest
from pathlib import Path

class ProductWorkspaceViewTests(unittest.TestCase):
    def test_main_contains_product_views(self):
        text=Path(__file__).resolve().parents[1].joinpath(
            "fabos_desktop","main.py").read_text(encoding="utf-8")
        self.assertIn('("Ready to Print","ready")', text)
        self.assertIn('("Needs Attention","attention")', text)
        self.assertIn('("Part Sets","part_sets")', text)
        self.assertIn('("Files","files")', text)

    def test_product_filters_are_distinct(self):
        text=Path(__file__).resolve().parents[1].joinpath(
            "fabos_desktop","main.py").read_text(encoding="utf-8")
        self.assertIn('group=="part_sets" and mode!="part_set"', text)
        self.assertIn('group=="files" and not has_files', text)

if __name__=="__main__":
    unittest.main()
