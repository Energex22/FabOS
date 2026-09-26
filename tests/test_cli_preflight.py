import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fabos_core.cli import _production_check


class ProductionPreflightTests(unittest.TestCase):
    def test_preflight_rejects_missing_production_configuration(self):
        with tempfile.TemporaryDirectory() as td:
            env = {
                "FABOS_DATA_DIR": str(Path(td) / "missing"),
                "FABOS_PAYMENT_PROVIDER": "stripe",
                "FABOS_API_HOST": "127.0.0.1",
                "FABOS_API_DOCS": "false",
            }
            with patch.dict(os.environ, env, clear=False):
                self.assertEqual(_production_check(), 1)


if __name__ == "__main__":
    unittest.main()
