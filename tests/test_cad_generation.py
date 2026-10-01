import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fabos_core.services import cad_generation as cad_module
from fabos_core.services.cad_generation import CadGenerationError, CadGenerationService


class CadGenerationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.service = CadGenerationService(settings=SimpleNamespace(data_dir=self.temp.name))

    def tearDown(self):
        self.temp.cleanup()

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_parse_prompt_and_generate_plate(self):
        result = self.service.generate(prompt="Create a 120 x 80 x 5 mm mounting plate with 4 5 mm holes.")
        self.assertEqual(result["spec"]["shape"], "mounting_plate")
        self.assertTrue(result["verification"]["passed"])
        self.assertTrue(all(item["pass"] for item in result["verification"]["holes"]))
        self.assertTrue(Path(next(a["path"] for a in result["artifacts"] if a["format"] == "stl")).is_file())
        self.assertTrue(Path(next(a["path"] for a in result["artifacts"] if a["format"] == "step")).is_file())

    def test_simple_revision_updates_existing_spec(self):
        original = {"shape": "plate", "dimensions": {"width": 100, "depth": 60, "height": 5}}
        revised = self.service._apply_simple_revision(original, "make the width 120 mm and thickness 6 mm")
        self.assertEqual(revised["dimensions"]["width"], 120.0)
        self.assertEqual(revised["dimensions"]["height"], 6.0)
        self.assertEqual(original["dimensions"]["width"], 100)

    def test_rejects_bad_hole_location(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({"shape": "plate", "dimensions": {"width": 50, "depth": 40, "height": 5},
                                         "holes": [{"diameter": 5, "x": 100, "y": 0}]})

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_ring_dimensions(self):
        result = self.service.generate(spec={"shape": "ring", "dimensions": {"outer_diameter": 40, "inner_diameter": 20, "height": 5}})
        self.assertTrue(result["verification"]["passed"])
        self.assertEqual(result["verification"]["checks"][0]["actual_mm"], 40.0)


if __name__ == "__main__":
    unittest.main()
