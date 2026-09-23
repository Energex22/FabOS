import tempfile
import unittest
from pathlib import Path
import zipfile

from fabos_core.services.customer_api_writes import _validate_model_file


class ModelUploadValidationTests(unittest.TestCase):
    def _temp(self, suffix, data):
        handle = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
        handle.write(data)
        handle.close()
        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))
        return handle.name

    def test_binary_stl_requires_size_matching_triangle_count(self):
        valid = b"\0" * 80 + (1).to_bytes(4, "little") + (b"\0" * 50)
        _validate_model_file(self._temp(".stl", valid), ".stl")

        invalid = b"\0" * 80 + (2).to_bytes(4, "little") + (b"\0" * 50)
        with self.assertRaisesRegex(ValueError, "does not match"):
            _validate_model_file(self._temp(".stl", invalid), ".stl")

    def test_ascii_stl_requires_geometry_markers(self):
        with self.assertRaisesRegex(ValueError, "ASCII STL"):
            _validate_model_file(self._temp(".stl", b"solid model\nendsolid model\n"), ".stl")

        valid = b"solid model\nfacet normal 0 0 0\nouter loop\nvertex 0 0 0\nendloop\nendfacet\nendsolid model\n"
        _validate_model_file(self._temp(".stl", valid), ".stl")

    def test_obj_requires_vertex_data_and_rejects_binary_nulls(self):
        with self.assertRaisesRegex(ValueError, "no vertices"):
            _validate_model_file(self._temp(".obj", b"# empty model\n"), ".obj")

        with self.assertRaisesRegex(ValueError, "Invalid OBJ"):
            _validate_model_file(self._temp(".obj", b"v 0 0 0\x00"), ".obj")

        _validate_model_file(self._temp(".obj", b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"), ".obj")

    def test_step_requires_part21_header(self):
        with self.assertRaisesRegex(ValueError, "STEP"):
            _validate_model_file(self._temp(".step", b"not a step file"), ".step")

        valid = b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
        _validate_model_file(self._temp(".step", valid), ".step")

    def test_3mf_must_be_a_valid_zip(self):
        with self.assertRaisesRegex(ValueError, "Invalid 3MF"):
            _validate_model_file(self._temp(".3mf", b"not a zip"), ".3mf")

        path = self._temp(".3mf", b"")
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
        _validate_model_file(path, ".3mf")


if __name__ == "__main__":
    unittest.main()
