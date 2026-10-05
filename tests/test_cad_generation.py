import sqlite3
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
        result = self.service.generate(prompt="Create a 120 x 80 x 5 mm mounting plate with 4 5 mm holes.", output_formats=["stl", "step", "3mf"])
        self.assertEqual(result["spec"]["shape"], "mounting_plate")
        self.assertTrue(result["verification"]["passed"])
        self.assertTrue(all(item["pass"] for item in result["verification"]["holes"]))
        self.assertTrue(Path(next(a["path"] for a in result["artifacts"] if a["format"] == "stl")).is_file())
        self.assertTrue(Path(next(a["path"] for a in result["artifacts"] if a["format"] == "step")).is_file())
        self.assertTrue(Path(next(a["path"] for a in result["artifacts"] if a["format"] == "3mf")).is_file())

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_slot_generation_produces_valid_model(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "slots": [{"length": 30, "width": 8, "x": 0, "y": 0, "angle": 45}],
        }, output_formats=["stl", "3mf"])
        self.assertTrue(result["verification"]["passed"])
        self.assertTrue(any(a["format"] == "stl" for a in result["artifacts"]))
        self.assertTrue(any(a["format"] == "3mf" for a in result["artifacts"]))
    def test_reference_cad_requires_confirmed_scale(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 100, "depth": 60, "height": 5},
                "metadata": {
                    "reference_analysis": True,
                    "scale_confirmed": False,
                    "scale_source": "none",
                    "missing_dimensions": ["hole spacing"],
                },
            })

    def test_reference_cad_requires_all_measurements_and_confirmations(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 100, "depth": 60, "height": 5},
                "metadata": {
                    "reference_analysis": True,
                    "scale_confirmed": True,
                    "scale_source": "user_measurement",
                    "missing_dimensions": [],
                    "feature_uncertainties": ["hole depth"],
                    "needs_user_confirmation": True,
                },
            })

    def test_reference_cad_accepts_fully_constrained_reference(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "metadata": {
                "reference_analysis": True,
                "scale_confirmed": True,
                "scale_source": "drawing_dimension",
                "missing_dimensions": [],
                "feature_uncertainties": [],
                "needs_user_confirmation": False,
            },
        })
        self.assertTrue(spec["metadata"]["reference_analysis"])

    def test_simple_revision_updates_existing_spec(self):
        original = {"shape": "plate", "dimensions": {"width": 100, "depth": 60, "height": 5}}
        revised = self.service._apply_simple_revision(original, "make the width 120 mm and thickness 6 mm")
        self.assertEqual(revised["dimensions"]["width"], 120.0)
        self.assertEqual(revised["dimensions"]["height"], 6.0)
        self.assertEqual(original["dimensions"]["width"], 100)

    def test_edge_treatment_spec_validation(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 80, "depth": 50, "height": 8},
            "edge_treatment": {"fillet_radius": 3},
        })
        self.assertEqual(spec["edge_treatment"]["fillet_radius"], 3.0)

    def test_rejects_multiple_edge_treatments(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 80, "depth": 50, "height": 8},
                "edge_treatment": {"fillet_radius": 3, "chamfer_distance": 1},
            })

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_fillet_generation_and_verification(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 80, "depth": 50, "height": 8},
            "edge_treatment": {"fillet_radius": 3},
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        treatment = next(item for item in result["verification"]["checks"] if item["measurement"] == "edge_treatment")
        self.assertEqual(treatment["type"], "fillet_radius")

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_chamfer_generation_and_verification(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 80, "depth": 50, "height": 8},
            "edge_treatment": {"chamfer_distance": 2},
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        treatment = next(item for item in result["verification"]["checks"] if item["measurement"] == "edge_treatment")
        self.assertEqual(treatment["type"], "chamfer_distance")

    def test_counterbore_hole_spec_validation(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 80, "depth": 50, "height": 8},
            "holes": [{"diameter": 4, "x": 10, "y": 5, "head_type": "counterbore", "head_diameter": 8, "head_depth": 3}],
        })
        hole = spec["holes"][0]
        self.assertEqual(hole["head_type"], "counterbore")
        self.assertEqual(hole["head_diameter"], 8.0)
        self.assertEqual(hole["head_depth"], 3.0)

    def test_rejects_invalid_hole_head(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 80, "depth": 50, "height": 8},
                "holes": [{"diameter": 8, "x": 0, "y": 0, "head_type": "counterbore", "head_diameter": 6, "head_depth": 3}],
            })

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_countersink_generation_verifies_head_geometry(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 80, "depth": 50, "height": 8},
            "holes": [{"diameter": 4, "x": 10, "y": 5, "head_type": "countersink", "head_diameter": 9, "head_depth": 2}],
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        hole = result["verification"]["holes"][0]
        self.assertEqual(hole["head_type"], "countersink")
        self.assertTrue(hole["head_diameter_pass"])
        self.assertTrue(hole["head_depth_pass"])
        self.assertAlmostEqual(hole["actual_head_diameter_mm"], 9.0, places=2)
        self.assertAlmostEqual(hole["actual_head_depth_mm"], 2.0, places=2)

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_counterbore_generation_verifies_head_geometry(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 80, "depth": 50, "height": 8},
            "holes": [{"diameter": 4, "x": 10, "y": 5, "head_type": "counterbore", "head_diameter": 8, "head_depth": 3}],
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        hole = result["verification"]["holes"][0]
        self.assertEqual(hole["head_type"], "counterbore")
        self.assertTrue(hole["head_diameter_pass"])
        self.assertTrue(hole["head_depth_pass"])
        self.assertAlmostEqual(hole["actual_head_diameter_mm"], 8.0, places=2)
        self.assertAlmostEqual(hole["actual_head_depth_mm"], 3.0, places=2)

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_counterbore_generation(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 80, "depth": 50, "height": 8},
            "holes": [{"diameter": 4, "x": 10, "y": 5, "head_type": "counterbore", "head_diameter": 8, "head_depth": 3}],
        }, output_formats=["stl", "step", "3mf"])
        self.assertTrue(result["verification"]["passed"])
        self.assertTrue(any(a["format"] == "3mf" for a in result["artifacts"]))

    def test_boss_spec_validation(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "bosses": [{"diameter": 12, "height": 8, "x": 20, "y": -10}],
        })
        self.assertEqual(spec["bosses"][0]["diameter"], 12.0)
        self.assertEqual(spec["bosses"][0]["height"], 8.0)

    def test_rejects_boss_outside_part(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 50, "depth": 40, "height": 5},
                "bosses": [{"diameter": 12, "height": 8, "x": 30, "y": 0}],
            })

    def test_rejects_boss_on_round_part(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "cylinder",
                "dimensions": {"diameter": 40, "height": 10},
                "bosses": [{"diameter": 12, "height": 8, "x": 0, "y": 0}],
            })

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_boss_generation_and_dimensions(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "bosses": [
                {"diameter": 12, "height": 8, "x": -20, "y": 0},
                {"diameter": 10, "height": 5, "x": 20, "y": 0},
            ],
        }, output_formats=["stl", "step", "3mf"])
        self.assertTrue(result["verification"]["passed"])
        height_check = next(item for item in result["verification"]["checks"] if item["measurement"] == "height_mm")
        self.assertEqual(height_check["expected_mm"], 13.0)
        self.assertEqual(height_check["actual_mm"], 13.0)
        self.assertTrue(any(a["format"] == "3mf" for a in result["artifacts"]))

    def test_slot_spec_validation(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "slots": [{"length": 30, "width": 8, "x": 0, "y": 0, "angle": 45}],
        })
        self.assertEqual(len(spec["slots"]), 1)
        self.assertEqual(spec["slots"][0]["width"], 8.0)

    def test_rejects_slots_on_round_part(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "flange",
                "dimensions": {"outer_diameter": 80, "bore_diameter": 20, "height": 8},
                "slots": [{"length": 20, "width": 6, "x": 0, "y": 0}],
            })
    def test_rejects_slot_outside_part(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 50, "depth": 40, "height": 5},
                "slots": [{"length": 30, "width": 8, "x": 30, "y": 0}],
            })
    def test_rejects_bad_hole_location(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({"shape": "plate", "dimensions": {"width": 50, "depth": 40, "height": 5},
                                         "holes": [{"diameter": 5, "x": 100, "y": 0}]})

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_flange_generation_and_bolt_pattern(self):
        result = self.service.generate(
            prompt="Create an 80 x 20 x 8 mm flange with a 20 mm bore and 4 bolt holes."
        )
        self.assertEqual(result["spec"]["shape"], "flange")
        self.assertEqual(len(result["spec"]["holes"]), 5)
        self.assertTrue(result["verification"]["passed"])
        self.assertTrue(all(item["pass"] for item in result["verification"]["holes"]))

    def test_job_history_is_scoped_to_user(self):
        db_file = Path(self.temp.name) / "cad.sqlite3"

        class Database:
            def connect(self):
                conn = sqlite3.connect(str(db_file))
                conn.row_factory = sqlite3.Row
                return conn

        with Database().connect() as conn:
            conn.execute("""CREATE TABLE cad_generation_jobs(
                id TEXT PRIMARY KEY,
                user_id TEXT,
                status TEXT,
                prompt TEXT,
                spec_json TEXT,
                verification_json TEXT,
                artifacts_json TEXT,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.execute(
                "INSERT INTO cad_generation_jobs(id,user_id,status,prompt,spec_json,verification_json,artifacts_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("job-a", "user-a", "completed", "A", '{"shape":"box"}', '{}', '[]'),
            )
            conn.execute(
                "INSERT INTO cad_generation_jobs(id,user_id,status,prompt,spec_json,verification_json,artifacts_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("job-b", "user-b", "completed", "B", '{"shape":"plate"}', '{}', '[]'),
            )
            conn.commit()

        service = CadGenerationService(settings=SimpleNamespace(data_dir=self.temp.name), database=Database())
        jobs = service.list_jobs("user-a")
        self.assertEqual([job["id"] for job in jobs], ["job-a"])
        self.assertEqual(jobs[0]["spec"]["shape"], "box")

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_revision_creates_parent_job_lineage(self):
        db_file = Path(self.temp.name) / "cad-lineage.sqlite3"

        class Database:
            def connect(self):
                conn = sqlite3.connect(str(db_file))
                conn.row_factory = sqlite3.Row
                return conn

        with Database().connect() as conn:
            conn.execute("""CREATE TABLE cad_generation_jobs(
                id TEXT PRIMARY KEY, user_id TEXT, status TEXT, prompt TEXT,
                spec_json TEXT, verification_json TEXT, artifacts_json TEXT,
                error TEXT, parent_job_id TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.commit()

        service = CadGenerationService(settings=SimpleNamespace(data_dir=self.temp.name), database=Database())
        first = service.generate(spec={"shape": "plate", "dimensions": {"width": 60, "depth": 40, "height": 5}}, output_formats=["step"], owner_id="user-a")
        revised = service.revise(first["job_id"], "make the width 70 mm", owner_id="user-a", output_formats=["step"])
        parent = service.get_job(revised["job_id"], owner_id="user-a")
        self.assertEqual(parent["parent_job_id"], first["job_id"])
        self.assertNotEqual(revised["job_id"], first["job_id"])
    def test_job_detail_isolated_by_owner(self):
        db_file = Path(self.temp.name) / "cad-detail.sqlite3"

        class Database:
            def connect(self):
                conn = sqlite3.connect(str(db_file))
                conn.row_factory = sqlite3.Row
                return conn

        with Database().connect() as conn:
            conn.execute("""CREATE TABLE cad_generation_jobs(
                id TEXT PRIMARY KEY,
                user_id TEXT,
                status TEXT,
                prompt TEXT,
                spec_json TEXT,
                verification_json TEXT,
                artifacts_json TEXT,
                error TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )""")
            conn.execute(
                "INSERT INTO cad_generation_jobs(id,user_id,status,prompt,spec_json,verification_json,artifacts_json) "
                "VALUES(?,?,?,?,?,?,?)",
                ("job-a", "user-a", "completed", "A", '{"shape":"box"}', '{}', '[]'),
            )
            conn.commit()

        service = CadGenerationService(settings=SimpleNamespace(data_dir=self.temp.name), database=Database())
        self.assertIsNotNone(service.get_job("job-a", owner_id="user-a"))
        self.assertIsNone(service.get_job("job-a", owner_id="user-b"))

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_preflight_rejects_model_that_exceeds_printer_volume(self):
        db_file = Path(self.temp.name) / "printer.sqlite3"

        class Database:
            def connect(self):
                conn = sqlite3.connect(str(db_file))
                conn.row_factory = sqlite3.Row
                return conn

        with Database().connect() as conn:
            conn.execute("""CREATE TABLE printers(
                id TEXT PRIMARY KEY,
                name TEXT,
                build_x_mm REAL,
                build_y_mm REAL,
                build_z_mm REAL
            )""")
            conn.execute(
                "INSERT INTO printers(id,name,build_x_mm,build_y_mm,build_z_mm) VALUES(?,?,?,?,?)",
                ("tiny", "Tiny Printer", 50, 50, 50),
            )
            conn.commit()

        service = CadGenerationService(settings=SimpleNamespace(data_dir=self.temp.name), database=Database())
        result = service.preflight(
            spec={"shape": "box", "dimensions": {"width": 80, "depth": 40, "height": 20}},
            printer_id="tiny",
        )
        self.assertFalse(result["printer"]["fits_build_volume"])
        self.assertFalse(result["printable"])
        self.assertTrue(result["warnings"])

    def test_counterbore_verification_reports_depth(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 60, "depth": 40, "height": 10},
            "holes": [{"diameter": 5, "x": 0, "y": 0, "head_type": "counterbore", "head_diameter": 10, "head_depth": 3}],
        })
        self.assertEqual(spec["holes"][0]["head_depth"], 3.0)

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_boss_verification_includes_height(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 60, "depth": 40, "height": 5},
            "bosses": [{"diameter": 10, "height": 8, "x": 0, "y": 0}],
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        check = next(c for c in result["verification"]["checks"] if c["measurement"] == "boss_features")
        self.assertTrue(check["details"][0]["height_pass"])

    def test_rejects_overlapping_holes(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 100, "depth": 60, "height": 5},
                "holes": [
                    {"diameter": 10, "x": 0, "y": 0},
                    {"diameter": 8, "x": 7, "y": 0},
                ],
            })

    def test_rejects_hole_overlapping_boss(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 100, "depth": 60, "height": 5},
                "holes": [{"diameter": 8, "x": 10, "y": 0}],
                "bosses": [{"diameter": 12, "height": 5, "x": 12, "y": 0}],
            })

    def test_rejects_hole_overlapping_internal_post(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
                "holes": [{"diameter": 8, "x": 10, "y": 0}],
                "internal_posts": [{"diameter": 12, "height": 20, "x": 12, "y": 0}],
            })

    def test_rejects_hole_outside_cylinder(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "cylinder",
                "dimensions": {"diameter": 40, "height": 10},
                "holes": [{"diameter": 5, "x": 25, "y": 0}],
            })

    def test_rejects_hole_inside_ring_bore(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "ring",
                "dimensions": {"outer_diameter": 40, "inner_diameter": 20, "height": 5},
                "holes": [{"diameter": 5, "x": 0, "y": 0}],
            })
    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_ring_dimensions(self):
        result = self.service.generate(spec={"shape": "ring", "dimensions": {"outer_diameter": 40, "inner_diameter": 20, "height": 5}})
        self.assertTrue(result["verification"]["passed"])
        self.assertEqual(result["verification"]["checks"][0]["actual_mm"], 40.0)


    def test_rib_and_tab_spec_validation(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "ribs": [{"length": 40, "width": 4, "height": 12, "x": 0, "y": 0, "angle": 15}],
            "tabs": [{"length": 20, "width": 10, "height": 3, "x": 30, "y": 20}],
        })
        self.assertEqual(spec["ribs"][0]["height"], 12.0)
        self.assertEqual(spec["ribs"][0]["angle"], 15.0)
        self.assertEqual(spec["tabs"][0]["length"], 20.0)

    def test_rejects_rib_outside_part(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 50, "depth": 40, "height": 5},
                "ribs": [{"length": 20, "width": 8, "height": 10, "x": 30, "y": 0}],
            })

    def test_rejects_tabs_on_round_part(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "cylinder",
                "dimensions": {"diameter": 40, "height": 10},
                "tabs": [{"length": 10, "width": 5, "height": 3, "x": 0, "y": 0}],
            })

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_rib_and_tab_generation(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "ribs": [{"length": 40, "width": 4, "height": 12, "x": 0, "y": 0}],
            "tabs": [{"length": 20, "width": 10, "height": 3, "x": 30, "y": 20}],
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        self.assertTrue(any(item["measurement"] == "rib_features" for item in result["verification"]["checks"]))
        self.assertTrue(any(item["measurement"] == "tab_features" for item in result["verification"]["checks"]))
        height_check = next(item for item in result["verification"]["checks"] if item["measurement"] == "height_mm")
        self.assertEqual(height_check["expected_mm"], 17.0)


    def test_rectangular_mounting_pattern_expands_to_holes(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "mounting_pattern": {"type": "rectangular", "diameter": 5, "spacing_x": 40, "spacing_y": 20, "count_x": 2, "count_y": 2},
        })
        self.assertEqual(len(spec["holes"]), 4)
        self.assertEqual(sorted((round(h["x"], 1), round(h["y"], 1)) for h in spec["holes"]),
                         [(-20.0, -10.0), (-20.0, 10.0), (20.0, -10.0), (20.0, 10.0)])

    def test_radial_mounting_pattern_expands_to_holes(self):
        spec = self.service.normalize_spec({
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 100, "height": 5},
            "mounting_pattern": {"type": "radial", "diameter": 4, "radius": 30, "count": 4},
        })
        self.assertEqual(len(spec["holes"]), 4)
        self.assertAlmostEqual(spec["holes"][0]["x"], 30.0, places=4)
        self.assertAlmostEqual(spec["holes"][1]["y"], 30.0, places=4)

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_mounting_pattern_generates_verified_geometry(self):
        result = self.service.generate(spec={
            "shape": "plate",
            "dimensions": {"width": 100, "depth": 60, "height": 5},
            "mounting_pattern": {"type": "rectangular", "diameter": 5, "spacing_x": 40, "spacing_y": 20, "count_x": 2, "count_y": 2},
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        self.assertEqual(len(result["verification"]["holes"]), 4)


    def test_enclosure_corner_radius_normalization(self):
        spec = self.service.normalize_spec({
            "shape": "enclosure",
            "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4, "corner_radius": 8},
        })
        self.assertEqual(spec["dimensions"]["corner_radius"], 8.0)

    def test_rejects_enclosure_corner_radius_that_consumes_wall(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 40, "depth": 30, "height": 20, "wall_thickness": 3, "corner_radius": 14},
            })

    def test_fallback_parser_recognizes_enclosure(self):
        spec = self.service.parse_prompt("Create a 100 x 80 x 40 mm enclosure with 3 mm walls")
        self.assertEqual(spec["shape"], "enclosure")
        self.assertEqual(spec["dimensions"]["width"], 100.0)
        self.assertEqual(spec["dimensions"]["wall_thickness"], 3.0)


    def test_enclosure_spec_validation(self):
        spec = self.service.normalize_spec({
            "shape": "enclosure",
            "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
        })
        self.assertEqual(spec["dimensions"]["wall_thickness"], 3.0)
        self.assertEqual(spec["dimensions"]["floor_thickness"], 4.0)

    def test_rejects_thick_enclosure_walls(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 40, "depth": 30, "height": 20, "wall_thickness": 20},
            })

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_enclosure_generation_and_dimensions(self):
        result = self.service.generate(spec={
            "shape": "enclosure",
            "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        self.assertEqual(result["verification"]["checks"][0]["actual_mm"], 100.0)
        self.assertEqual(result["verification"]["checks"][1]["actual_mm"], 80.0)
        self.assertEqual(result["verification"]["checks"][2]["actual_mm"], 40.0)


    def test_printability_constraints_warn_by_default(self):
        spec = self.service.normalize_spec({
            "shape": "enclosure",
            "dimensions": {"width": 60, "depth": 50, "height": 30, "wall_thickness": 0.5},
            "print_constraints": {"nozzle_diameter": 0.4, "min_wall_thickness": 1.0},
        })
        self.assertTrue(spec["metadata"]["printability_warnings"])

    def test_printability_constraints_strict_reject(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 60, "depth": 50, "height": 3},
                "holes": [{"diameter": 0.3, "x": 0, "y": 0}],
                "print_constraints": {"min_feature_size": 0.8, "strict": True},
            })

    def test_enclosure_internal_features_validation(self):
        spec = self.service.normalize_spec({
            "shape": "enclosure",
            "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
            "internal_posts": [{"diameter": 10, "height": 20, "x": -30, "y": -20, "bore_diameter": 4}],
            "dividers": [{"length": 50, "thickness": 3, "height": 25, "x": 0, "y": 0, "angle": 90}],
            "cable_openings": [{"side": "front", "width": 12, "height": 8, "offset": 10, "z": 15}],
            "lid_interface": {"lip_height": 2, "clearance": 0.25, "lip_wall": 2},
        })
        self.assertEqual(len(spec["internal_posts"]), 1)
        self.assertEqual(spec["internal_posts"][0]["bore_diameter"], 4.0)
        self.assertEqual(len(spec["dividers"]), 1)
        self.assertEqual(len(spec["cable_openings"]), 1)
        self.assertEqual(spec["cable_openings"][0]["side"], "front")
        self.assertEqual(spec["lid_interface"]["clearance"], 0.25)

    def test_rejects_enclosure_features_on_non_enclosure(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 100, "depth": 60, "height": 5},
                "internal_posts": [{"diameter": 10, "x": 0, "y": 0}],
            })
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "plate",
                "dimensions": {"width": 100, "depth": 60, "height": 5},
                "cable_openings": [{"side": "front", "width": 10, "height": 5}],
            })

    def test_rejects_invalid_cable_opening(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
                "cable_openings": [{"side": "top", "width": 10, "height": 5}],
            })
    
    def test_rejects_rotated_divider_that_exceeds_interior(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 60, "depth": 50, "height": 30, "wall_thickness": 3, "floor_thickness": 4},
                "dividers": [{"length": 65, "thickness": 4, "height": 20, "x": 0, "y": 0, "angle": 45}],
            })

    def test_rejects_cable_opening_outside_wall_span(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
                "cable_openings": [{"side": "front", "width": 12, "height": 8, "offset": 50, "z": 15}],
            })

    def test_rejects_internal_post_above_enclosure_interior(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
                "internal_posts": [{"diameter": 10, "height": 37, "x": 0, "y": 0}],
            })

    def test_rejects_internal_post_overlapping_divider(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
                "internal_posts": [{"diameter": 10, "height": 20, "x": 0, "y": 0}],
                "dividers": [{"length": 50, "thickness": 4, "height": 20, "x": 0, "y": 0, "angle": 0}],
            })

    def test_rejects_overlapping_enclosure_dividers(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
                "dividers": [
                    {"length": 50, "thickness": 4, "height": 20, "x": 0, "y": 0, "angle": 0},
                    {"length": 40, "thickness": 4, "height": 20, "x": 10, "y": 0, "angle": 90},
                ],
            })

    def test_allows_non_overlapping_rotated_enclosure_dividers(self):
        spec = self.service.normalize_spec({
            "shape": "enclosure",
            "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
            "dividers": [
                {"length": 30, "thickness": 4, "height": 20, "x": -25, "y": 0, "angle": 0},
                {"length": 30, "thickness": 4, "height": 20, "x": 25, "y": 0, "angle": 45},
            ],
        })
        self.assertEqual(len(spec["dividers"]), 2)

    def test_rejects_lid_lip_wall_that_collapses_interface(self):
        with self.assertRaises(CadGenerationError):
            self.service.normalize_spec({
                "shape": "enclosure",
                "dimensions": {"width": 40, "depth": 30, "height": 20, "wall_thickness": 3, "floor_thickness": 4},
                "lid_interface": {"lip_height": 2, "clearance": 0.25, "lip_wall": 14},
            })

    @unittest.skipUnless(cad_module.cq is not None, "CadQuery optional dependency is not installed")
    def test_enclosure_internal_features_generation(self):
        result = self.service.generate(spec={
            "shape": "enclosure",
            "dimensions": {"width": 100, "depth": 80, "height": 40, "wall_thickness": 3, "floor_thickness": 4},
            "internal_posts": [
                {"diameter": 10, "height": 20, "x": -30, "y": -20, "bore_diameter": 4},
                {"diameter": 10, "height": 20, "x": 30, "y": -20, "bore_diameter": 4},
            ],
            "dividers": [{"length": 50, "thickness": 3, "height": 25, "x": 0, "y": 0}],
            "cable_openings": [{"side": "front", "width": 12, "height": 8, "offset": 10, "z": 15}],
            "lid_interface": {"lip_height": 2, "clearance": 0.25, "lip_wall": 2},
        }, output_formats=["step"])
        self.assertTrue(result["verification"]["passed"])
        post_check = next(c for c in result["verification"]["checks"] if c["measurement"] == "internal_post_features")
        self.assertEqual(post_check["actual"], 2)
        self.assertTrue(all(item["pass"] for item in post_check["details"]))
        divider_check = next(c for c in result["verification"]["checks"] if c["measurement"] == "divider_geometry")
        opening_check = next(c for c in result["verification"]["checks"] if c["measurement"] == "cable_opening_geometry")
        lid_check = next(c for c in result["verification"]["checks"] if c["measurement"] == "lid_interface_geometry")
        self.assertEqual(divider_check["requested"], 1)
        self.assertGreater(divider_check["volume_delta_mm3"], 0)
        self.assertTrue(divider_check["pass"])
        self.assertEqual(opening_check["requested"], 1)
        self.assertGreater(opening_check["volume_delta_mm3"], 0)
        self.assertTrue(opening_check["pass"])
        self.assertTrue(lid_check["requested"])
        self.assertGreater(lid_check["volume_delta_mm3"], 0)
        self.assertTrue(lid_check["pass"])



if __name__ == "__main__":
    unittest.main()
