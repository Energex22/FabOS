import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from fabos_core.services.recovery import RecoveryService


class RecoverySessionTests(unittest.TestCase):
    def test_clean_shutdown_removes_runtime_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            app = SimpleNamespace(settings=SimpleNamespace(data_dir=Path(tmp)))
            recovery = RecoveryService(app)
            self.assertTrue(recovery.marker.exists())
            recovery.clean_shutdown()
            self.assertFalse(recovery.marker.exists())


if __name__ == "__main__":
    unittest.main()
